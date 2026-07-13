"""REE subprocess runner for reproducible specialist inference.

Builds a deterministic argv list for the Gensyn REE shell script and invokes
it without a shell. All user-supplied data flows through file paths or separate
list elements — never through shell-string concatenation.

Real CLI (github.com/gensyn-ai/ree — ree.sh):
    ree.sh \\
      --model-name <hf-model-id> \\
      --prompt-file <jsonl-path> \\
      --max-new-tokens 300

ree.sh defaults to the 'run-all' subcommand; passing no subcommand is fine.
It runs inside Docker and writes its receipt to:
    ~/.cache/gensyn/<model-slug>/<task-id>/metadata/receipt_<timestamp>.json

Set GENSYN_SDK_COMMAND to the full path of ree.sh (e.g. /opt/ree/ree.sh).
The default is 'ree.sh' which works if the repo is on PATH or in the CWD.

Docker + CUDA driver are required for the real SDK. In test/CI environments,
substitute a fake runner via the runner= constructor argument.

Hash algorithm note: receipt validation checks supported SHA-256/Keccak content
hashes and mirrors Gensyn REE v0.2.0's SHA-256 commitment over pipe-delimited
component hashes. If a future REE version changes an algorithm,
receipt_status falls back to "parsed".
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.ree.receipts import ReeReceipt, parse_ree_receipt
from app.ree.validator import ReeValidationResult, validate_ree_receipt


SubprocessRunner = Callable[..., Any]

_DEFAULT_CACHE_DIR = Path.home() / ".cache"


@dataclass(frozen=True)
class ReeRunRequest:
    """Inputs for one reproducible REE inference call."""

    model_name: str
    prompt: str
    max_new_tokens: int = 300
    cpu_only: bool = False


@dataclass(frozen=True)
class ReeRunOutcome:
    """Parsed REE receipt plus local validation result."""

    receipt: ReeReceipt
    validation: ReeValidationResult
    receipt_path: Path
    receipt_status: str


class ReeRunnerError(RuntimeError):
    """Raised when the REE subprocess or its output is unusable."""


class ReeRunner:
    """Build deterministic argv lists and execute REE without a shell."""

    def __init__(
        self,
        *,
        command: str = "ree.sh",
        runner: SubprocessRunner | None = None,
        cache_dir: Path | None = None,
        cpu_only: bool = False,
    ) -> None:
        if not command or not isinstance(command, str):
            raise ValueError("REE runner command must be a non-empty string")
        self._command = command
        self._runner = runner or subprocess.run
        self._cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self._cpu_only = cpu_only

    @property
    def command(self) -> str:
        return self._command

    def build_args(
        self,
        request: ReeRunRequest,
        *,
        prompt_path: Path,
    ) -> list[str]:
        """Return the argv list for one REE invocation.

        Every user-supplied value lives in its own list element so that no
        shell metacharacter can be reinterpreted as a flag or chained command.
        """
        if not request.model_name:
            raise ValueError("ReeRunRequest.model_name must be a non-empty string")

        args = [
            self._command,
            "--model-name",
            request.model_name,
            "--prompt-file",
            str(prompt_path),
            "--max-new-tokens",
            str(request.max_new_tokens),
        ]
        if self._cpu_only or request.cpu_only:
            args.append("--cpu-only")
        return args

    def run(
        self, request: ReeRunRequest, *, workspace: Path | None = None
    ) -> ReeRunOutcome:
        """Execute one REE call and return the parsed receipt with validation."""
        if workspace is None:
            with tempfile.TemporaryDirectory(prefix="signal-count-ree-") as tmp:
                return self._run_in(Path(tmp), request)
        workspace.mkdir(parents=True, exist_ok=True)
        return self._run_in(workspace, request)

    def _run_in(self, workspace: Path, request: ReeRunRequest) -> ReeRunOutcome:
        prompt_path = workspace / "prompt.jsonl"
        prompt_path.write_text(
            json.dumps({"prompt": request.prompt}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _make_prompt_mount_readable(prompt_path)

        args = self.build_args(request, prompt_path=prompt_path)

        existing = self._snapshot_receipts()

        try:
            self._runner(
                args,
                check=True,
                capture_output=True,
                text=True,
                shell=False,
            )
        except subprocess.CalledProcessError as exc:
            raise ReeRunnerError(
                f"REE subprocess failed with exit code {exc.returncode}"
                f"{_format_subprocess_output(exc)}"
            ) from exc
        except FileNotFoundError as exc:
            raise ReeRunnerError(
                "REE command was not found. Clone github.com/gensyn-ai/ree and set "
                "GENSYN_SDK_COMMAND to the full path of ree.sh."
            ) from exc

        receipt_path = self._find_new_receipt(existing)
        receipt = parse_ree_receipt(receipt_path)
        validation = validate_ree_receipt(receipt)
        receipt_status = "validated" if validation.matches else "parsed"
        return ReeRunOutcome(
            receipt=receipt,
            validation=validation,
            receipt_path=receipt_path,
            receipt_status=receipt_status,
        )

    def _snapshot_receipts(self) -> set[Path]:
        """Collect all receipt paths that exist before a run."""
        gensyn_cache = self._cache_dir / "gensyn"
        if not gensyn_cache.exists():
            return set()
        return set(gensyn_cache.glob("**/receipt_*.json"))

    def _find_new_receipt(self, before: set[Path]) -> Path:
        """Return the receipt written by the most recent run."""
        gensyn_cache = self._cache_dir / "gensyn"
        after = (
            set(gensyn_cache.glob("**/receipt_*.json"))
            if gensyn_cache.exists()
            else set()
        )
        new_receipts = sorted(after - before)
        if new_receipts:
            return new_receipts[-1]
        # Fall back to the newest overall receipt if nothing new appeared.
        all_receipts = sorted(after)
        if all_receipts:
            return all_receipts[-1]
        raise ReeRunnerError(
            f"REE did not produce a receipt in {gensyn_cache}. "
            "Check that ree.sh completed successfully and Docker is available."
        )


def _format_subprocess_output(exc: subprocess.CalledProcessError) -> str:
    """Return a compact stdout/stderr suffix for failed REE invocations."""
    parts = []
    for label, value in (("stdout", exc.stdout), ("stderr", exc.stderr)):
        if not value:
            continue
        text = str(value).strip()
        if not text:
            continue
        lines = text.splitlines()
        tail = "\n".join(lines[-20:])
        parts.append(f"{label}:\n{tail}")
    if not parts:
        return ""
    return "\n" + "\n".join(parts)


def _make_prompt_mount_readable(prompt_path: Path) -> None:
    """Allow the container user to traverse the prompt dir and read the file."""
    prompt_dir = prompt_path.parent
    prompt_dir.chmod(prompt_dir.stat().st_mode | 0o111)
    prompt_path.chmod(prompt_path.stat().st_mode | 0o444)
