import re
from pathlib import Path


CI_PATH = Path(".github/workflows/ci.yml")
FULL_BATTLE_SCRIPT = Path("scripts/run_full_battle_demo.sh")
LATEST_ARTIFACT_SCRIPT = Path("scripts/verify_latest_artifact.sh")
SUBMISSION_PACK_SCRIPT = Path("scripts/export_submission_pack.sh")
ARTIFACT_REPLAY_SCRIPT = Path("scripts/replay_full_battle_artifact.sh")


def test_ci_workflow_targets_python_app_and_tests() -> None:
    content = CI_PATH.read_text(encoding="utf-8")

    assert 'python-version: "3.11"' in content
    assert (
        "python -m pip install --require-hashes --only-binary=:all: "
        "-r requirements-lock.txt" in content
    )
    assert "python -m pip install --no-deps --no-build-isolation -e ." in content
    assert "python -m pip check" in content
    assert "ruff check app/ tests/ scripts/*.py" in content
    assert "ruff format --check app/ tests/ scripts/*.py" in content
    assert "python -m pytest tests/ -q --tb=short" in content
    assert (
        "python scripts/build_public_evidence.py --verify "
        "evidence/public-fixture-v1" in content
    )


def test_ci_workflow_uses_placeholder_env_values() -> None:
    content = CI_PATH.read_text(encoding="utf-8")

    assert 'SIGNAL_COUNT_ENV: "test"' in content
    assert 'LLM_API_KEY: "test-key"' in content
    assert "${{ secrets." in content
    assert "sk-" not in content


def test_ci_workflow_has_read_only_permissions_and_bounded_runtime() -> None:
    content = CI_PATH.read_text(encoding="utf-8")

    assert content.index("  pull_request:") < content.index("permissions:")
    assert "permissions:\n  contents: read" in content
    assert "runs-on: ubuntu-24.04" in content
    assert "timeout-minutes: 15" in content
    assert "actions/checkout@93cb6efe18208431cddfb8368fd83d5badbf9bfd # v5" in content
    assert "persist-credentials: false" in content
    assert (
        "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6" in content
    )
    assert "actions/checkout@v" not in content
    assert "actions/setup-python@v" not in content
    remote_uses = [
        line.split("#", 1)[0].strip()
        for line in content.splitlines()
        if line.strip().startswith("- uses:") and "./" not in line
    ]
    assert remote_uses
    assert all(
        re.fullmatch(r"- uses: [^@\s]+@[0-9a-f]{40}", line) for line in remote_uses
    )


def test_full_battle_script_has_valid_shebang_and_preflight_mode() -> None:
    content = FULL_BATTLE_SCRIPT.read_text(encoding="utf-8")
    raw = FULL_BATTLE_SCRIPT.read_bytes()

    assert raw.startswith(b"#!/usr/bin/env bash\n")
    assert "PREFLIGHT_ONLY=0" in content
    assert "--preflight-only" in content
    assert "FULL_BATTLE_JOB_TIMEOUT_SECONDS" in content
    assert "Usage: scripts/run_full_battle_demo.sh [--preflight-only]" in content


def test_full_battle_preflight_documents_required_checks() -> None:
    content = FULL_BATTLE_SCRIPT.read_text(encoding="utf-8")

    for expected in (
        "check_command curl",
        "check_command docker",
        "check_command forge",
        "check_command git",
        "check_command openssl",
        "check_file_executable",
        "check_env_value GENSYN_RPC_URL",
        "DEPLOYER_PRIVATE_KEY or CHAIN_WRITER_PRIVATE_KEY",
        "Missing Gensyn REE checkout",
        "Missing REE Docker image",
        "check_docker_image gensyn-axl-local",
        "check_port_free",
    ):
        assert expected in content


def test_positioning_copy_uses_verification_language() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    template = Path("app/templates/index.html").read_text(encoding="utf-8")

    required = "Do not trust the memo. Verify every specialist behind it."
    assert required in readme
    assert required in template
    assert "LLM wrapper" not in readme
    assert "Dispatch Agent Swarm" not in template
    assert "AI swarm" not in template


def test_demo_runbook_contains_judge_first_script() -> None:
    runbook = Path("docs/demo-runbook.md").read_text(encoding="utf-8")

    assert "Target 90-second flow after prewarm" in runbook
    assert "30-second sponsor pitch" in runbook
    assert "Completed proof console with active `Verify Run` tab" in runbook
    assert "Do not trust the memo. Verify every specialist behind it." in runbook
    assert "decision support, not trading advice" in runbook


def test_latest_artifact_rehearsal_script_documents_required_checks() -> None:
    content = LATEST_ARTIFACT_SCRIPT.read_text(encoding="utf-8")
    raw = LATEST_ARTIFACT_SCRIPT.read_bytes()

    assert raw.startswith(b"#!/usr/bin/env bash\n")
    assert "Usage: scripts/verify_latest_artifact.sh [--require-live]" in content
    assert "SIGNAL_COUNT_BATTLE_RUNTIME_DIR" in content
    assert "SIGNAL_COUNT_PROOF_CONSOLE_URL" in content
    assert "job-after-indexer.json" in content
    assert "index-after-indexer.html" in content
    assert "signal_count.db" in content
    assert "rehearsal-report.json" in content
    assert "/jobs/${JOB_ID}/verify" in content
    assert "artifact-only rehearsal passed" in content
    assert "REQUIRE_LIVE" in content


def test_submission_pack_exporter_documents_artifacts() -> None:
    content = SUBMISSION_PACK_SCRIPT.read_text(encoding="utf-8")
    raw = SUBMISSION_PACK_SCRIPT.read_bytes()

    assert raw.startswith(b"#!/usr/bin/env bash\n")
    assert "Usage: scripts/export_submission_pack.sh" in content
    assert "SIGNAL_COUNT_BATTLE_RUNTIME_DIR" in content
    assert "SIGNAL_COUNT_SUBMISSION_EXPORT_DIR" in content
    assert "summary.txt" in content
    assert "job-after-indexer.json" in content
    assert "index-after-indexer.html" in content
    assert "rehearsal-report.json" in content
    assert "verify-live.json" in content
    assert "tx-links.txt" in content
    assert "SUBMISSION_NOTES.md" in content
    assert "manifest.json" in content
    assert "Claim Boundaries" in content


def test_saved_artifact_replay_verifier_documents_limits() -> None:
    content = ARTIFACT_REPLAY_SCRIPT.read_text(encoding="utf-8")
    raw = ARTIFACT_REPLAY_SCRIPT.read_bytes()

    assert raw.startswith(b"#!/usr/bin/env bash\n")
    assert "Usage: scripts/replay_full_battle_artifact.sh [job-json-path]" in content
    assert "artifact-replay-report.json" in content
    assert "specialist_responses" in content
    assert "ree_receipt_body" in content
    assert "ree_receipt_path" in content
    assert "present_only" in content
    assert "saved artifact lacks material needed for repeat validation" in content
    assert "saved artifact replay does not query RPC" in content
