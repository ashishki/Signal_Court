"""Credential-free deterministic signed-run evidence builder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.axl.registry import AXLCapabilityRegistry, AXLRegistry
from app.chain.explorer import explorer_tx_url
from app.config.settings import Settings
from app.evaluation.attestations import verify_verification_attestation
from app.identity.signing import (
    sign_agent_execution,
    verify_signed_execution,
    wallet_address_from_private_key,
)
from app.nodes.verifier.service import VerifierService
from app.ree.claims import check_receipt_claim
from app.schemas.contracts import (
    AgentIdentity,
    SpecialistResponse,
    TaskSpec,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "app/evidence/fixtures/public_signed_run.json"
REE_RECEIPT_PATH = ROOT / "app/ree/fixtures/synthetic_public_receipt.json"
TESTNET_SOURCE_PATH = ROOT / "docs/gensyn-contracts.md"
LOCK_PATH = ROOT / "requirements-lock.txt"
EXPLORER_BASE_URL = "https://gensyn-testnet.explorer.alchemy.com"
ROLE_SETTING_PREFIX = {
    "regime": "regime",
    "narrative": "narrative",
    "risk": "risk",
}


def build_public_evidence() -> dict[str, Any]:
    """Build a deterministic artifact from repository application modules."""

    fixture = _read_json(FIXTURE_PATH)
    receipt_body = _read_json(REE_RECEIPT_PATH)
    task = TaskSpec.model_validate(fixture["task"])
    topology = fixture["topology"]
    roles = fixture["roles"]
    registry = AXLRegistry(_settings_for_roles(roles))
    capabilities = AXLCapabilityRegistry(registry)
    verifier = VerifierService(
        verifier_private_key=_fixture_private_key("verifier"),
        ree_policy="risk-only-ree",
        enforce_ree_policy=True,
    )

    routes: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    attestations: list[dict[str, Any]] = []
    receipt_checks: list[dict[str, Any]] = []
    execution_signatures_valid = 0
    attestation_signatures_valid = 0

    for role_fixture in roles:
        role = str(role_fixture["role"])
        candidates = capabilities.list_candidates(role, topology_snapshot=topology)
        selection = capabilities.select_for_role(role, topology_snapshot=topology)
        private_key = _fixture_private_key(role)
        wallet = wallet_address_from_private_key(private_key)
        response_values = dict(role_fixture["response"])
        if role == "risk":
            response_values.update(
                {
                    "ree_receipt_hash": receipt_body["receipt_hash"],
                    "receipt_status": "validated",
                    "ree_prompt_hash": receipt_body["prompt_hash"],
                    "ree_tokens_hash": receipt_body["tokens_hash"],
                    "ree_model_name": receipt_body["model_name"],
                    "ree_receipt_body": receipt_body,
                }
            )
        response = SpecialistResponse(
            job_id=task.job_id,
            node_role=role,
            peer_id=selection.service.peer_id,
            agent_wallet=wallet,
            **response_values,
        )
        execution = sign_agent_execution(
            task=task,
            response=response,
            identity=AgentIdentity(
                role=role,
                peer_id=selection.service.peer_id,
                wallet=wallet,
            ),
            private_key=private_key,
        )
        attestation = verifier.verify_signed_execution(execution)
        execution_valid = verify_signed_execution(execution)
        attestation_valid = verify_verification_attestation(attestation)
        receipt_check = check_receipt_claim(response)
        execution_signatures_valid += int(execution_valid)
        attestation_signatures_valid += int(attestation_valid)

        routes.append(
            {
                "role": role,
                "candidates": [
                    {
                        "peer_id": candidate.peer_id,
                        "service_name": candidate.service_name,
                        "health": candidate.health,
                        "reputation_score": candidate.reputation_score,
                    }
                    for candidate in candidates
                ],
                "selected_peer_id": selection.service.peer_id,
                "selected_service_name": selection.service.service_name,
                "selection_reason": selection.reason,
                "dispatch_target": (
                    f"/mcp/{selection.service.peer_id}/{selection.service.service_name}"
                ),
                "dispatch_executed": False,
            }
        )
        executions.append(execution.model_dump(mode="json"))
        attestations.append(attestation.model_dump(mode="json"))
        receipt_checks.append({"role": role, **receipt_check.to_dict()})

    testnet_references = _build_testnet_references(
        fixture["historical_testnet_references"]
    )
    all_attestations_accepted = all(
        item["status"] == "accepted" for item in attestations
    )
    all_receipt_claims_valid = all(item["valid"] for item in receipt_checks)
    all_checks_passed = all(
        (
            execution_signatures_valid == len(roles),
            attestation_signatures_valid == len(roles),
            all_attestations_accepted,
            all_receipt_claims_valid,
        )
    )
    if not all_checks_passed:
        raise ValueError("public fixture failed one or more verification checks")

    return {
        "schema": "signal-count.public-signed-run-evidence/v1",
        "mode": "credential-free-deterministic-fixture",
        "source_fixture": {
            "path": FIXTURE_PATH.relative_to(ROOT).as_posix(),
            "sha256": _sha256_file(FIXTURE_PATH),
        },
        "task": task.model_dump(mode="json"),
        "topology": topology,
        "routing_selection": routes,
        "signed_executions": executions,
        "verifier_attestations": attestations,
        "receipt_claim_checks": receipt_checks,
        "historical_testnet_provenance": {
            "network": "Gensyn Testnet",
            "chain_id": 685685,
            "source": TESTNET_SOURCE_PATH.relative_to(ROOT).as_posix(),
            "source_sha256": _sha256_file(TESTNET_SOURCE_PATH),
            "network_lookup_performed": False,
            "references": testnet_references,
        },
        "verification_summary": {
            "signed_executions": len(executions),
            "valid_execution_signatures": execution_signatures_valid,
            "signed_verifier_attestations": len(attestations),
            "valid_verifier_signatures": attestation_signatures_valid,
            "all_attestations_accepted": all_attestations_accepted,
            "all_receipt_claims_valid": all_receipt_claims_valid,
            "all_checks_passed": all_checks_passed,
        },
        "claim_boundaries": [
            "All thesis, topology, responses, identities, and keys are public synthetic fixtures.",
            "Routing selection used the repository application capability registry; no AXL dispatch or live network call ran.",
            "The REE-shaped receipt is synthetic; validated binds its prompt, parameters, and text output to component hashes and the component hashes to the master commitment, but is not model inference or external re-execution.",
            "Commit/config source bytes and non-content receipt metadata are not locally reconstructed; the signed fixture envelope binds the serialized response, not a real REE identity.",
            "No testnet transaction was submitted or queried; deployment transactions are historical documentation references only.",
            "This artifact is not evidence of users, production operation, trading performance, economic security, or protocol security.",
        ],
        "reproduction": {
            "install_commands": [
                "python -m pip install --require-hashes --only-binary=:all: -r requirements-lock.txt",
                "python -m pip install --no-deps --no-build-isolation -e .",
            ],
            "build_command": (
                "python scripts/build_public_evidence.py "
                "--out evidence/public-fixture-v1"
            ),
            "verify_command": (
                "python scripts/build_public_evidence.py "
                "--verify evidence/public-fixture-v1"
            ),
            "credentials_required": [],
            "dependency_lock": LOCK_PATH.relative_to(ROOT).as_posix(),
            "dependency_lock_sha256": _sha256_file(LOCK_PATH),
        },
    }


def build_environment_record() -> dict[str, Any]:
    """Return the exact environment recorded for the canonical tracked bundle."""

    return {
        "schema": "signal-count.evidence-environment/v1",
        "canonical_generation_environment": {
            "operating_system": "Ubuntu 24.04",
            "kernel": "Linux 6.17.0-35-generic",
            "architecture": "x86_64",
            "python": "CPython 3.12.3",
            "dependency_lock": "requirements-lock.txt",
            "dependency_lock_sha256": _sha256_file(LOCK_PATH),
            "dependency_lock_mode": "version-and-sha256",
            "build_toolchain": _locked_build_toolchain(),
        },
        "runtime_contract": {
            "python": ">=3.11",
            "network_required": False,
            "credentials_required": [],
        },
        "limitations": [
            "This environment record is provenance for the canonical bytes, not a remote attestation.",
            "Semantic verification is expected to remain deterministic on supported Python versions with the locked dependencies.",
        ],
    }


def render_json(value: Any) -> bytes:
    """Render stable human-readable JSON bytes."""

    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def build_manifest(evidence_bytes: bytes, environment_bytes: bytes) -> dict[str, Any]:
    """Bind artifact bytes to the code and public sources that produced them."""

    source_paths = (
        FIXTURE_PATH,
        REE_RECEIPT_PATH,
        TESTNET_SOURCE_PATH,
        LOCK_PATH,
        ROOT / "app/axl/registry.py",
        ROOT / "app/chain/explorer.py",
        ROOT / "app/config/settings.py",
        ROOT / "app/evidence/public_fixture.py",
        ROOT / "app/evaluation/attestations.py",
        ROOT / "app/evaluation/scoring.py",
        ROOT / "app/identity/canonical.py",
        ROOT / "app/identity/hashing.py",
        ROOT / "app/identity/signing.py",
        ROOT / "app/nodes/verifier/service.py",
        ROOT / "app/ree/claims.py",
        ROOT / "app/ree/receipts.py",
        ROOT / "app/ree/validator.py",
        ROOT / "app/schemas/contracts.py",
        ROOT / ".github/workflows/ci.yml",
        ROOT / "pyproject.toml",
        ROOT / "requirements-dev.txt",
        ROOT / "requirements.txt",
        ROOT / "scripts/build_public_evidence.py",
    )
    evidence_digest = _sha256_bytes(evidence_bytes)
    return {
        "schema": "signal-count.public-evidence-manifest/v1",
        "artifact": {
            "path": "evidence.json",
            "sha256": evidence_digest,
            "content_address": f"sha256:{evidence_digest}",
        },
        "environment": {
            "path": "environment.json",
            "sha256": _sha256_bytes(environment_bytes),
        },
        "sources": {
            path.relative_to(ROOT).as_posix(): _sha256_file(path)
            for path in source_paths
        },
        "verification_command": (
            "python scripts/build_public_evidence.py "
            "--verify evidence/public-fixture-v1"
        ),
    }


def write_bundle(output_dir: Path) -> dict[str, Any]:
    """Write the canonical evidence, environment, and checksum manifest."""

    evidence_bytes = render_json(build_public_evidence())
    environment_bytes = render_json(build_environment_record())
    manifest = build_manifest(evidence_bytes, environment_bytes)
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {"evidence.json", "environment.json", "manifest.json"}
    unexpected = {path.name for path in output_dir.iterdir()} - expected_names
    if unexpected:
        raise ValueError(f"unexpected evidence bundle entries: {sorted(unexpected)}")
    (output_dir / "evidence.json").write_bytes(evidence_bytes)
    (output_dir / "environment.json").write_bytes(environment_bytes)
    (output_dir / "manifest.json").write_bytes(render_json(manifest))
    return manifest


def verify_bundle(output_dir: Path) -> dict[str, Any]:
    """Regenerate and verify every tracked byte and source checksum."""

    evidence_bytes = render_json(build_public_evidence())
    environment_bytes = render_json(build_environment_record())
    expected_manifest = build_manifest(evidence_bytes, environment_bytes)
    expected_files = {
        "evidence.json": evidence_bytes,
        "environment.json": environment_bytes,
        "manifest.json": render_json(expected_manifest),
    }
    actual_entries = {path.name for path in output_dir.iterdir()}
    if actual_entries != set(expected_files):
        raise ValueError(
            "evidence bundle file set differs: "
            f"expected={sorted(expected_files)}, actual={sorted(actual_entries)}"
        )
    for name, expected in expected_files.items():
        path = output_dir / name
        if not path.is_file():
            raise ValueError(f"missing evidence bundle file: {path}")
        if path.read_bytes() != expected:
            raise ValueError(f"evidence bundle file does not reproduce: {path}")
    return expected_manifest


def _settings_for_roles(roles: list[dict[str, Any]]) -> Settings:
    values: dict[str, Any] = {}
    for role_fixture in roles:
        role = str(role_fixture["role"])
        prefix = ROLE_SETTING_PREFIX[role]
        service_name = str(role_fixture["service_name"])
        candidates = [str(value) for value in role_fixture["candidates"]]
        values[f"{prefix}_peer_id"] = candidates[0]
        values[f"{prefix}_service_name"] = service_name
        values[f"{prefix}_peer_candidates"] = ",".join(
            f"{peer_id}|{service_name}" for peer_id in candidates
        )
    return Settings(**values)


def _locked_build_toolchain() -> dict[str, str]:
    """Read canonical build-tool versions from the bound hash lock."""

    lock_lines = LOCK_PATH.read_text(encoding="utf-8").splitlines()
    versions: dict[str, str] = {}
    for package in ("pip", "setuptools", "wheel"):
        prefix = f"{package}=="
        matches = [line.split()[0] for line in lock_lines if line.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(f"expected exactly one locked {package} requirement")
        versions[package] = matches[0].removeprefix(prefix)
    return versions


def _build_testnet_references(
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_text = TESTNET_SOURCE_PATH.read_text(encoding="utf-8")
    built: list[dict[str, Any]] = []
    for reference in references:
        tx_hash = str(reference["deployment_transaction"])
        address = str(reference["address"])
        explorer_url = explorer_tx_url(tx_hash, EXPLORER_BASE_URL)
        if any(value not in source_text for value in (tx_hash, address, explorer_url)):
            raise ValueError(
                "testnet reference is not bound to docs/gensyn-contracts.md"
            )
        built.append(
            {
                **reference,
                "explorer_url": explorer_url,
                "status": "documented_historical_reference",
                "rpc_receipt_reverified": False,
            }
        )
    return built


def _fixture_private_key(label: str) -> str:
    # Public deterministic fixture material. Never use this derivation for funds.
    return (
        "0x"
        + hashlib.sha256(
            f"signal-count-public-fixture-key:{label}".encode("utf-8")
        ).hexdigest()
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
