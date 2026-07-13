"""Tamper checks for signed specialist executions."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from eth_utils import to_checksum_address

from app.identity.hashing import canonical_json_hash
from app.identity.signing import recover_execution_signer
from app.ree.claims import check_receipt_claim
from app.schemas.contracts import SignedAgentExecution, SpecialistResponse, TaskSpec


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str
    expected: str | None = None
    observed: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DetectionResult:
    status: str
    checks: list[CheckResult] = field(default_factory=list)
    failed_check_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "failed_check_names": list(self.failed_check_names),
            "checks": [check.to_dict() for check in self.checks],
        }


def output_hash_for_response(response: SpecialistResponse) -> str:
    return canonical_json_hash(response)


def task_hash_for_task(task: TaskSpec) -> str:
    return canonical_json_hash(task)


def detect_tampering(execution: SignedAgentExecution) -> DetectionResult:
    checks: list[CheckResult] = []

    checks.append(_check_output_hash(execution))
    checks.append(_check_task_hash(execution))
    checks.append(_check_identity_role(execution))
    checks.append(_check_identity_peer_id(execution))
    checks.append(_check_signer_matches_identity(execution))
    checks.append(_check_response_wallet_matches_identity(execution))
    checks.append(_check_signature_recovers_signer(execution))
    checks.append(_check_receipt_consistency(execution))
    checks.append(_check_signature_algorithm(execution))

    failed = [check.name for check in checks if not check.passed]
    return DetectionResult(
        status="clean" if not failed else "tampered",
        checks=checks,
        failed_check_names=failed,
    )


def _check_output_hash(execution: SignedAgentExecution) -> CheckResult:
    claimed = execution.signature.output_hash
    recomputed = output_hash_for_response(execution.response)
    return CheckResult(
        name="output_hash_match",
        passed=claimed.lower() == recomputed.lower(),
        detail="response body must canonical-hash to envelope.output_hash",
        expected=claimed,
        observed=recomputed,
    )


def _check_task_hash(execution: SignedAgentExecution) -> CheckResult:
    claimed = execution.signature.task_hash
    recomputed = task_hash_for_task(execution.task)
    return CheckResult(
        name="task_hash_match",
        passed=claimed.lower() == recomputed.lower(),
        detail="task body must canonical-hash to envelope.task_hash",
        expected=claimed,
        observed=recomputed,
    )


def _check_identity_role(execution: SignedAgentExecution) -> CheckResult:
    return CheckResult(
        name="identity_role_match",
        passed=execution.identity.role == execution.response.node_role,
        detail="identity.role must equal response.node_role",
        expected=execution.identity.role,
        observed=execution.response.node_role,
    )


def _check_identity_peer_id(execution: SignedAgentExecution) -> CheckResult:
    return CheckResult(
        name="identity_peer_id_match",
        passed=execution.identity.peer_id == execution.response.peer_id,
        detail="identity.peer_id must equal response.peer_id",
        expected=execution.identity.peer_id,
        observed=execution.response.peer_id,
    )


def _check_signer_matches_identity(execution: SignedAgentExecution) -> CheckResult:
    signer = execution.signature.signer
    wallet = execution.identity.wallet
    return CheckResult(
        name="signer_equals_identity_wallet",
        passed=signer.lower() == wallet.lower(),
        detail="envelope.signer must equal identity.wallet",
        expected=wallet,
        observed=signer,
    )


def _check_response_wallet_matches_identity(
    execution: SignedAgentExecution,
) -> CheckResult:
    identity_wallet = to_checksum_address(execution.identity.wallet)
    response_wallet = execution.response.agent_wallet
    matches = response_wallet is None or (
        to_checksum_address(response_wallet) == identity_wallet
    )
    return CheckResult(
        name="response_wallet_matches_identity",
        passed=matches,
        detail=(
            "response.agent_wallet must be absent or equal the signed identity wallet"
        ),
        expected=identity_wallet,
        observed=(
            to_checksum_address(response_wallet)
            if response_wallet is not None
            else "not_declared"
        ),
    )


def _check_signature_recovers_signer(execution: SignedAgentExecution) -> CheckResult:
    claimed = execution.signature.signer
    try:
        recovered = recover_execution_signer(execution)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="signature_recovers_signer",
            passed=False,
            detail=f"signature recovery raised: {exc}",
            expected=claimed,
            observed=None,
        )
    return CheckResult(
        name="signature_recovers_signer",
        passed=to_checksum_address(claimed).lower() == recovered.lower(),
        detail="EIP-191 recovery must return envelope.signer",
        expected=to_checksum_address(claimed),
        observed=recovered,
    )


def _check_receipt_consistency(execution: SignedAgentExecution) -> CheckResult:
    check = check_receipt_claim(execution.response)
    return CheckResult(
        name="receipt_consistency",
        passed=check.valid,
        detail=(
            "receipt claim material passed fail-closed validation"
            if check.valid
            else f"receipt claim failed: {','.join(check.reasons)}"
        ),
        expected="valid embedded evidence for the claimed receipt status",
        observed=check.status,
    )


def _check_signature_algorithm(execution: SignedAgentExecution) -> CheckResult:
    algorithm = execution.signature.algorithm
    return CheckResult(
        name="signature_algorithm_supported",
        passed=algorithm == "eip191",
        detail="only eip191 signatures are accepted",
        expected="eip191",
        observed=algorithm,
    )
