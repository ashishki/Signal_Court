"""Tests for the REE subprocess runner."""

from __future__ import annotations

import json
import stat
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.identity.hashing import keccak256_hex
from app.ree.receipts import compute_receipt_hash
from app.ree.runner import ReeRunner, ReeRunnerError, ReeRunRequest


def _build_request(model_name: str = "Qwen/Qwen3-0.6B") -> ReeRunRequest:
    return ReeRunRequest(
        model_name=model_name,
        prompt="Stress test the thesis. Return JSON only.",
        max_new_tokens=300,
    )


def _make_valid_receipt(model_name: str, prompt_path: Path) -> dict:
    prompt = json.loads(prompt_path.read_text(encoding="utf-8"))["prompt"]
    commit_hash = keccak256_hex(f"model:{model_name}".encode())
    config_hash = keccak256_hex(b'{"max_new_tokens":300}')
    prompt_hash = keccak256_hex(prompt.encode("utf-8"))
    parameters_hash = keccak256_hex(b'{"max_new_tokens":300}')
    text_output = "stub REE output"
    tokens_hash = keccak256_hex(text_output.encode("utf-8"))
    receipt_hash = compute_receipt_hash(
        commit_hash=commit_hash,
        config_hash=config_hash,
        prompt_hash=prompt_hash,
        parameters_hash=parameters_hash,
        tokens_hash=tokens_hash,
    )
    return {
        "model_name": model_name,
        "commit_hash": commit_hash,
        "config_hash": config_hash,
        "prompt": prompt,
        "prompt_hash": prompt_hash,
        "parameters": {"max_new_tokens": 300},
        "parameters_hash": parameters_hash,
        "tokens_hash": tokens_hash,
        "token_count": 8,
        "finish_reason": "eos_token",
        "text_output": text_output,
        "device_type": "cpu",
        "device_name": "test-cpu",
        "receipt_hash": receipt_hash,
        "version": "1.0",
        "ree_version": "0.2.0",
    }


def test_ree_runner_builds_safe_args(tmp_path: Path) -> None:
    runner = ReeRunner(command="ree.sh")
    unsafe_model = "evil; rm -rf / #"
    request = _build_request(model_name=unsafe_model)

    prompt_path = tmp_path / "prompt.txt"

    args = runner.build_args(request, prompt_path=prompt_path)

    assert isinstance(args, list)
    assert all(isinstance(arg, str) for arg in args)
    assert args[0] == "ree.sh"
    assert "--model-name" in args
    assert args[args.index("--model-name") + 1] == unsafe_model
    assert "--prompt-file" in args
    assert args[args.index("--prompt-file") + 1] == str(prompt_path)
    assert "--max-new-tokens" in args

    # No --task-dir or --operation-set (not part of real ree.sh interface).
    assert "--task-dir" not in args
    assert "--operation-set" not in args

    assert ";" not in args[0]
    assert "&&" not in args[0]

    # Shell metacharacters in the model name land in exactly one list element.
    assert sum(unsafe_model in a for a in args) == 1
    assert any(a == unsafe_model for a in args)


def test_ree_runner_cpu_only_flag(tmp_path: Path) -> None:
    runner = ReeRunner(command="ree.sh", cpu_only=True)
    args = runner.build_args(_build_request(), prompt_path=tmp_path / "p.txt")
    assert "--cpu-only" in args

    runner_no_cpu = ReeRunner(command="ree.sh", cpu_only=False)
    args_no = runner_no_cpu.build_args(_build_request(), prompt_path=tmp_path / "p.txt")
    assert "--cpu-only" not in args_no

    # cpu_only on the request also triggers the flag
    req_cpu = ReeRunRequest(model_name="Qwen/Qwen3-0.6B", prompt="x", cpu_only=True)
    args_req = runner_no_cpu.build_args(req_cpu, prompt_path=tmp_path / "p.txt")
    assert "--cpu-only" in args_req


def test_ree_runner_disallows_empty_command() -> None:
    with pytest.raises(ValueError):
        ReeRunner(command="")


def test_ree_runner_disallows_empty_model(tmp_path: Path) -> None:
    runner = ReeRunner(command="ree.sh")
    bad = ReeRunRequest(model_name="", prompt="x")
    with pytest.raises(ValueError):
        runner.build_args(bad, prompt_path=tmp_path / "p.txt")


def test_ree_runner_run_invokes_subprocess_without_shell(tmp_path: Path) -> None:
    """run() with a stubbed subprocess: writes prompt, discovers receipt, validates."""
    captured: dict[str, object] = {}
    cache_dir = tmp_path / "cache"
    request = _build_request()

    def fake_runner(args, **kwargs):
        captured["args"] = list(args)
        captured["kwargs"] = dict(kwargs)

        prompt_path = Path(args[args.index("--prompt-file") + 1])
        prompt_line = json.loads(prompt_path.read_text(encoding="utf-8"))
        assert prompt_path.name == "prompt.jsonl"
        assert prompt_line == {"prompt": request.prompt}
        model_name = args[args.index("--model-name") + 1]

        # Simulate ree.sh writing receipt to ~/.cache/gensyn/<model>/metadata/
        model_slug = model_name.replace("/", "--")
        metadata_dir = cache_dir / "gensyn" / model_slug / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        receipt_data = _make_valid_receipt(model_name, prompt_path)
        (metadata_dir / "receipt_20260427_120000.json").write_text(
            json.dumps(receipt_data), encoding="utf-8"
        )

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    runner = ReeRunner(command="ree.sh", runner=fake_runner, cache_dir=cache_dir)
    outcome = runner.run(request, workspace=tmp_path / "ws")

    assert captured["kwargs"]["shell"] is False
    assert isinstance(captured["args"], list)
    assert captured["args"][0] == "ree.sh"
    assert outcome.validation.matches is True
    assert outcome.receipt.text_output == "stub REE output"
    assert outcome.receipt_status == "validated"


def test_ree_runner_makes_prompt_mount_readable(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    workspace = tmp_path / "private-ws"
    workspace.mkdir(mode=0o700)
    captured: dict[str, int] = {}

    def fake_runner(args, **kwargs):
        prompt_path = Path(args[args.index("--prompt-file") + 1])
        captured["dir_mode"] = stat.S_IMODE(prompt_path.parent.stat().st_mode)
        captured["file_mode"] = stat.S_IMODE(prompt_path.stat().st_mode)

        model_name = args[args.index("--model-name") + 1]
        metadata_dir = cache_dir / "gensyn" / "Qwen--Qwen3-0.6B" / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        (metadata_dir / "receipt_20260427_140000.json").write_text(
            json.dumps(_make_valid_receipt(model_name, prompt_path)),
            encoding="utf-8",
        )

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    runner = ReeRunner(command="ree.sh", runner=fake_runner, cache_dir=cache_dir)
    runner.run(_build_request(), workspace=workspace)

    assert captured["dir_mode"] & 0o111 == 0o111
    assert captured["file_mode"] & 0o444 == 0o444


def test_ree_runner_marks_parsed_when_hash_mismatches(tmp_path: Path) -> None:
    """Runner sets receipt_status='parsed' when the receipt hash does not match."""
    cache_dir = tmp_path / "cache"

    def fake_runner(args, **kwargs):
        model_name = args[args.index("--model-name") + 1]
        model_slug = model_name.replace("/", "--")
        metadata_dir = cache_dir / "gensyn" / model_slug / "metadata"
        metadata_dir.mkdir(parents=True, exist_ok=True)
        (metadata_dir / "receipt_20260427_130000.json").write_text(
            json.dumps(
                {
                    "model_name": "Qwen/Qwen3-0.6B",
                    "commit_hash": "0x" + "11" * 32,
                    "config_hash": "0x" + "22" * 32,
                    "prompt": _build_request().prompt,
                    "prompt_hash": "0x" + "33" * 32,
                    "parameters": {"max_new_tokens": 300},
                    "parameters_hash": "0x" + "44" * 32,
                    "tokens_hash": "0x" + "55" * 32,
                    "token_count": 1,
                    "finish_reason": "eos_token",
                    "text_output": "stub",
                    "device_type": "cpu",
                    "device_name": "test",
                    "receipt_hash": "0x" + "de" * 32,
                    "version": "1.0",
                    "ree_version": "0.2.0",
                }
            ),
            encoding="utf-8",
        )

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Result()

    runner = ReeRunner(command="ree.sh", runner=fake_runner, cache_dir=cache_dir)
    outcome = runner.run(_build_request(), workspace=tmp_path / "ws2")

    assert outcome.validation.matches is False
    assert outcome.receipt_status == "parsed"
    assert outcome.receipt.receipt_hash == "0x" + "de" * 32


def test_ree_runner_never_reuses_stale_receipt(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    request = _build_request()
    prompt_path = tmp_path / "stale-prompt.jsonl"
    prompt_path.write_text(
        json.dumps({"prompt": request.prompt}) + "\n",
        encoding="utf-8",
    )
    metadata_dir = cache_dir / "gensyn" / "Qwen--Qwen3-0.6B" / "metadata"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "receipt_stale.json").write_text(
        json.dumps(_make_valid_receipt(request.model_name, prompt_path)),
        encoding="utf-8",
    )

    runner = ReeRunner(
        command="ree.sh",
        runner=lambda *args, **kwargs: None,
        cache_dir=cache_dir,
    )

    with pytest.raises(ReeRunnerError, match="exactly one new receipt"):
        runner.run(request, workspace=tmp_path / "workspace")


def test_ree_runner_selects_only_new_receipt_bound_to_request(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    request = _build_request()

    def fake_runner(args, **kwargs):
        prompt_path = Path(args[args.index("--prompt-file") + 1])
        metadata_dir = cache_dir / "gensyn" / "mixed" / "metadata"
        metadata_dir.mkdir(parents=True)
        unrelated = _make_valid_receipt("Qwen/unrelated", prompt_path)
        matching = _make_valid_receipt(request.model_name, prompt_path)
        (metadata_dir / "receipt_unrelated.json").write_text(
            json.dumps(unrelated),
            encoding="utf-8",
        )
        (metadata_dir / "receipt_matching.json").write_text(
            json.dumps(matching),
            encoding="utf-8",
        )

    runner = ReeRunner(command="ree.sh", runner=fake_runner, cache_dir=cache_dir)

    outcome = runner.run(request, workspace=tmp_path / "workspace")

    assert outcome.receipt.model_name == request.model_name
    assert outcome.receipt.prompt == request.prompt
    assert outcome.receipt.parameters["max_new_tokens"] == request.max_new_tokens
    assert outcome.receipt_path.name == "receipt_matching.json"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_name", "Qwen/unrelated"),
        ("prompt", "different prompt"),
        ("max_new_tokens", 301),
        ("device_type", "cuda"),
    ],
)
def test_ree_runner_rejects_new_receipt_with_wrong_invocation_claim(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    cache_dir = tmp_path / "cache"
    request = _build_request()
    if field == "device_type":
        request = ReeRunRequest(
            model_name=request.model_name,
            prompt=request.prompt,
            max_new_tokens=request.max_new_tokens,
            cpu_only=True,
        )

    def fake_runner(args, **kwargs):
        prompt_path = Path(args[args.index("--prompt-file") + 1])
        receipt = _make_valid_receipt(request.model_name, prompt_path)
        if field == "max_new_tokens":
            receipt["parameters"]["max_new_tokens"] = value
        else:
            receipt[field] = value
        metadata_dir = cache_dir / "gensyn" / "wrong" / "metadata"
        metadata_dir.mkdir(parents=True)
        (metadata_dir / "receipt_wrong.json").write_text(
            json.dumps(receipt),
            encoding="utf-8",
        )

    runner = ReeRunner(command="ree.sh", runner=fake_runner, cache_dir=cache_dir)

    with pytest.raises(ReeRunnerError, match="bound to this invocation"):
        runner.run(request, workspace=tmp_path / "workspace")


def test_ree_runner_fails_closed_on_multiple_matching_new_receipts(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "cache"
    request = _build_request()

    def fake_runner(args, **kwargs):
        prompt_path = Path(args[args.index("--prompt-file") + 1])
        receipt = _make_valid_receipt(request.model_name, prompt_path)
        metadata_dir = cache_dir / "gensyn" / "ambiguous" / "metadata"
        metadata_dir.mkdir(parents=True)
        for suffix in ("one", "two"):
            (metadata_dir / f"receipt_{suffix}.json").write_text(
                json.dumps(receipt),
                encoding="utf-8",
            )

    runner = ReeRunner(command="ree.sh", runner=fake_runner, cache_dir=cache_dir)

    with pytest.raises(ReeRunnerError, match="attribution is ambiguous"):
        runner.run(request, workspace=tmp_path / "workspace")


def test_ree_runner_serializes_invocations_sharing_cache(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_runner(args, **kwargs):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            prompt_path = Path(args[args.index("--prompt-file") + 1])
            model_name = args[args.index("--model-name") + 1]
            metadata_dir = (
                cache_dir / "gensyn" / model_name.replace("/", "--") / "metadata"
            )
            metadata_dir.mkdir(parents=True)
            (metadata_dir / "receipt_concurrent.json").write_text(
                json.dumps(_make_valid_receipt(model_name, prompt_path)),
                encoding="utf-8",
            )
        finally:
            with counter_lock:
                active -= 1

    runner = ReeRunner(command="ree.sh", runner=fake_runner, cache_dir=cache_dir)
    requests = [_build_request("Qwen/one"), _build_request("Qwen/two")]
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda pair: runner.run(pair[1], workspace=pair[0]),
                [
                    (tmp_path / "workspace-one", requests[0]),
                    (tmp_path / "workspace-two", requests[1]),
                ],
            )
        )

    assert max_active == 1
    assert {outcome.receipt.model_name for outcome in outcomes} == {
        "Qwen/one",
        "Qwen/two",
    }


def test_ree_runner_failure_includes_subprocess_output(tmp_path: Path) -> None:
    def fake_runner(args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=args,
            output="stdout detail",
            stderr="stderr detail",
        )

    runner = ReeRunner(command="ree.sh", runner=fake_runner, cache_dir=tmp_path)

    with pytest.raises(ReeRunnerError) as exc_info:
        runner.run(_build_request(), workspace=tmp_path / "ws3")

    message = str(exc_info.value)
    assert "exit code 1" in message
    assert "stdout detail" in message
    assert "stderr detail" in message
