import hashlib
import json
import tomllib
from pathlib import Path

import pytest

from app.evidence.public_fixture import (
    build_environment_record,
    build_public_evidence,
    render_json,
    verify_bundle,
    write_bundle,
)

TRACKED_BUNDLE = Path("evidence/public-fixture-v1")
README = Path("README.md")
EVIDENCE_INDEX = Path("docs/evidence/README.md")
PROOF_ISSUE_TEMPLATE = Path(".github/ISSUE_TEMPLATE/proof-verification-defect.yml")


def test_public_evidence_builder_is_deterministic_and_fail_closed() -> None:
    first = build_public_evidence()
    second = build_public_evidence()

    assert render_json(first) == render_json(second)
    assert first["verification_summary"] == {
        "signed_executions": 3,
        "valid_execution_signatures": 3,
        "signed_verifier_attestations": 3,
        "valid_verifier_signatures": 3,
        "all_attestations_accepted": True,
        "all_receipt_claims_valid": True,
        "all_checks_passed": True,
    }
    assert all(
        route["dispatch_executed"] is False for route in first["routing_selection"]
    )
    assert first["historical_testnet_provenance"]["network_lookup_performed"] is False


def test_public_evidence_does_not_publish_fixture_private_keys() -> None:
    serialized = render_json(build_public_evidence()).decode("utf-8")

    assert "private_key" not in serialized
    assert "CHAIN_WRITER_PRIVATE_KEY" not in serialized
    assert "DEPLOYER_PRIVATE_KEY" not in serialized


def test_bundle_writer_and_verifier_detect_drift(tmp_path: Path) -> None:
    output_dir = tmp_path / "bundle"
    manifest = write_bundle(output_dir)

    assert verify_bundle(output_dir) == manifest
    evidence = json.loads((output_dir / "evidence.json").read_text())
    evidence["verification_summary"]["all_checks_passed"] = False
    (output_dir / "evidence.json").write_text(json.dumps(evidence))

    try:
        verify_bundle(output_dir)
    except ValueError as exc:
        assert "does not reproduce" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("tampered evidence bundle was accepted")


def test_bundle_verifier_rejects_unexpected_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "bundle"
    write_bundle(output_dir)
    (output_dir / "untracked-claim.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="file set differs"):
        verify_bundle(output_dir)


def test_bundle_writer_rejects_preexisting_unexpected_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "bundle"
    output_dir.mkdir()
    (output_dir / "untracked-claim.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected evidence bundle entries"):
        write_bundle(output_dir)


def test_recorded_build_toolchain_matches_lock_and_build_system() -> None:
    toolchain = build_environment_record()["canonical_generation_environment"][
        "build_toolchain"
    ]
    lock_text = Path("requirements-lock.txt").read_text(encoding="utf-8")
    build_requires = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))[
        "build-system"
    ]["requires"]

    assert set(toolchain) == {"pip", "setuptools", "wheel"}
    for package, version in toolchain.items():
        assert f"{package}=={version} \\" in lock_text
    assert f"setuptools=={toolchain['setuptools']}" in build_requires
    assert f"wheel=={toolchain['wheel']}" in build_requires


def test_tracked_public_evidence_bundle_reproduces() -> None:
    manifest = verify_bundle(TRACKED_BUNDLE)
    manifest_bytes = (TRACKED_BUNDLE / "manifest.json").read_bytes()
    manifest_address = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"
    readme = README.read_text(encoding="utf-8")
    index = EVIDENCE_INDEX.read_text(encoding="utf-8")

    assert manifest["artifact"]["content_address"] in readme
    assert manifest["artifact"]["content_address"] in index
    assert manifest_address in index
    for source in (
        "app/axl/registry.py",
        "app/identity/signing.py",
        "app/evaluation/attestations.py",
        "app/nodes/verifier/service.py",
        "app/ree/claims.py",
        "app/ree/validator.py",
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "requirements-dev.txt",
        "requirements.txt",
    ):
        assert source in manifest["sources"]


def test_reviewer_path_and_negative_claims_are_explicit() -> None:
    readme = README.read_text(encoding="utf-8")
    index = EVIDENCE_INDEX.read_text(encoding="utf-8")

    assert "## Five-minute Public Evidence Path" in readme
    assert "credential-free-deterministic-fixture" in (
        TRACKED_BUNDLE / "evidence.json"
    ).read_text(encoding="utf-8")
    assert "No ignored database" in index
    for boundary in (
        "not evidence of live networking",
        "users",
        "production operation",
        "economic security",
        "protocol security",
    ):
        assert boundary in index


def test_proof_defect_issue_form_forbids_private_artifacts() -> None:
    template = PROOF_ISSUE_TEMPLATE.read_text(encoding="utf-8")

    assert "Evidence content address" in template
    assert "Do not attach keys" in template
    assert "ignored runtime artifacts" in template
