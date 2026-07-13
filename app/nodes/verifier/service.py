"""Verifier service for signed specialist executions."""

from __future__ import annotations

from eth_account import Account

from app.evaluation.attestations import (
    verification_attestation_hash,
    verification_attestation_message,
)
from app.evaluation.scoring import score_specialist_response
from app.identity.hashing import canonical_json_hash
from app.identity.signing import verify_signed_execution
from app.ree.claims import canonical_validated_receipt_body, check_receipt_claim
from app.schemas.contracts import (
    SignedAgentExecution,
    SpecialistResponse,
    TaskSpec,
    VerificationAttestation,
)


class VerifierService:
    """Score specialist outputs and reject invalid execution envelopes."""

    def __init__(
        self,
        *,
        acceptance_threshold: float = 0.5,
        verifier_private_key: str = "",
        ree_policy: str = "risk-only-ree",
        enforce_ree_policy: bool = False,
    ) -> None:
        if enforce_ree_policy:
            _required_ree_roles(ree_policy)
        self._acceptance_threshold = acceptance_threshold
        self._verifier_private_key = verifier_private_key
        self._ree_policy = ree_policy
        self._enforce_ree_policy = enforce_ree_policy

    def run_metadata(self) -> dict[str, object]:
        return {
            "ree_policy": self._ree_policy,
            "ree_policy_enforced": self._enforce_ree_policy,
        }

    def verify_signed_execution(
        self,
        signed_execution: SignedAgentExecution,
    ) -> VerificationAttestation:
        task = signed_execution.task
        identity = signed_execution.identity
        response = signed_execution.response
        if not verify_signed_execution(signed_execution):
            context_reasons = _execution_context_failure_reasons(
                signed_execution=signed_execution
            )
            return self._sign_if_configured(
                VerificationAttestation(
                    job_id=task.job_id,
                    node_role=identity.role,
                    peer_id=identity.peer_id,
                    status="rejected",
                    score=0.0,
                    reasons=context_reasons or ["invalid_signature"],
                    signer=signed_execution.signature.signer,
                    agent_wallet=None,
                    output_hash=signed_execution.signature.output_hash,
                )
            )

        return self._verify_response(
            task=task,
            response=response,
            verified_signer=signed_execution.signature.signer,
            verified_output_hash=signed_execution.signature.output_hash,
        )

    def verify_response(
        self,
        *,
        task: TaskSpec,
        response: SpecialistResponse,
    ) -> VerificationAttestation:
        """Score an unsigned response without attributing it to a wallet."""

        return self._verify_response(task=task, response=response)

    def _verify_response(
        self,
        *,
        task: TaskSpec,
        response: SpecialistResponse,
        verified_signer: str | None = None,
        verified_output_hash: str | None = None,
    ) -> VerificationAttestation:
        if task.job_id != response.job_id:
            return self._sign_if_configured(
                VerificationAttestation(
                    job_id=task.job_id,
                    node_role=response.node_role,
                    peer_id=response.peer_id,
                    status="rejected",
                    score=0.0,
                    reasons=["task_response_job_id_mismatch"],
                    signer=verified_signer,
                    agent_wallet=None,
                    output_hash=verified_output_hash,
                )
            )

        breakdown = score_specialist_response(response, task)
        score = breakdown.total
        reasons = _score_reasons(response=response, score=score)
        receipt_check = check_receipt_claim(response)
        if not receipt_check.valid:
            score = min(score, self._acceptance_threshold - 0.01)
            reasons.extend(
                f"invalid_receipt_claim:{reason}" for reason in receipt_check.reasons
            )
            reasons.append(f"receipt_claim_gate={score:.4f}")
        required_ree_failure = self._required_ree_failure(
            response=response,
            receipt_status=receipt_check.status,
            receipt_valid=receipt_check.valid,
        )
        if required_ree_failure is not None:
            score = min(score, self._acceptance_threshold - 0.01)
            reasons.append(f"{required_ree_failure}:{self._ree_policy}")
        status = "accepted" if score >= self._acceptance_threshold else "rejected"
        if status == "rejected":
            reasons.append("score_below_threshold")
        canonical_receipt_body = canonical_validated_receipt_body(
            response,
            receipt_check=receipt_check,
        )

        return self._sign_if_configured(
            VerificationAttestation(
                job_id=response.job_id,
                node_role=response.node_role,
                peer_id=response.peer_id,
                status=status,
                score=score,
                reasons=reasons,
                signer=verified_signer,
                agent_wallet=verified_signer,
                output_hash=verified_output_hash or canonical_json_hash(response),
                ree_receipt_hash=response.ree_receipt_hash,
                receipt_status=response.receipt_status,
                ree_prompt_hash=response.ree_prompt_hash,
                ree_tokens_hash=response.ree_tokens_hash,
                ree_model_name=response.ree_model_name,
                ree_receipt_body=canonical_receipt_body,
                ree_receipt_path=response.ree_receipt_path,
            )
        )

    def verify_responses(
        self,
        *,
        task: TaskSpec,
        responses: list[SpecialistResponse],
    ) -> list[VerificationAttestation]:
        return [
            self.verify_response(task=task, response=response) for response in responses
        ]

    def _required_ree_failure(
        self,
        *,
        response: SpecialistResponse,
        receipt_status: str,
        receipt_valid: bool,
    ) -> str | None:
        if not self._enforce_ree_policy:
            return None
        required_roles = _required_ree_roles(self._ree_policy)
        if response.node_role not in required_roles:
            return None
        if not receipt_valid:
            return "required_ree_invalid"
        if receipt_status == "not_claimed":
            return "required_ree_missing"
        if receipt_status != "validated":
            return "required_ree_not_validated"
        return None

    def _sign_if_configured(
        self,
        attestation: VerificationAttestation,
    ) -> VerificationAttestation:
        if not self._verifier_private_key:
            return attestation

        attestation_hash = verification_attestation_hash(attestation)
        signer = Account.from_key(self._verifier_private_key).address
        message = verification_attestation_message(attestation_hash)
        signed = Account.sign_message(message, private_key=self._verifier_private_key)
        return attestation.model_copy(
            update={
                "verifier": signer,
                "attestation_hash": attestation_hash,
                "verifier_signature": f"0x{signed.signature.hex()}",
                "signature_algorithm": "eip191",
            }
        )


def _score_reasons(response: SpecialistResponse, score: float) -> list[str]:
    reasons = [f"deterministic_score={score:.4f}"]
    if response.receipt_status:
        reasons.append(f"receipt_status={response.receipt_status}")
    if response.citations:
        reasons.append("citations_present")
    if response.risks:
        reasons.append("risks_present")
    return reasons


def _execution_context_failure_reasons(
    *,
    signed_execution: SignedAgentExecution,
) -> list[str]:
    task = signed_execution.task
    identity = signed_execution.identity
    response = signed_execution.response
    reasons: list[str] = []
    if task.job_id != response.job_id:
        reasons.append("task_response_job_id_mismatch")
    if identity.role != response.node_role:
        reasons.append("identity_response_role_mismatch")
    if identity.peer_id != response.peer_id:
        reasons.append("identity_response_peer_id_mismatch")
    return reasons


def _required_ree_roles(ree_policy: str) -> set[str]:
    normalized = ree_policy.strip().lower().replace("_", "-")
    if normalized == "risk-only-ree":
        return {"risk"}
    if normalized == "all-llm-ree":
        return {"narrative", "risk"}
    raise ValueError(f"unsupported REE policy: {ree_policy}")
