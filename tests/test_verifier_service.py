import json
from pathlib import Path

from eth_account import Account
from eth_account.messages import encode_defunct

from app.evaluation.attestations import verify_verification_attestation
from app.identity.canonical import canonical_json_bytes
from app.identity.signing import sign_agent_execution
from app.nodes.verifier.service import VerifierService
from app.schemas.contracts import (
    AgentIdentity,
    ScenarioView,
    SignedAgentExecution,
    SpecialistResponse,
    TaskSpec,
)

TEST_PRIVATE_KEY = "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
TEST_WALLET = "0xFCAd0B19bB29D4674531d6f115237E16AfCE377c"
SYNTHETIC_RECEIPT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "ree"
    / "fixtures"
    / "synthetic_public_receipt.json"
)


def test_verifier_scores_valid_execution() -> None:
    signed = sign_agent_execution(
        task=_task(),
        response=_response(),
        identity=AgentIdentity(
            role="risk",
            peer_id="peer-risk-1",
            wallet=TEST_WALLET,
        ),
        private_key=TEST_PRIVATE_KEY,
    )

    attestation = VerifierService().verify_signed_execution(signed)

    assert attestation.status == "accepted"
    assert attestation.score > 0
    assert attestation.signer == TEST_WALLET
    assert attestation.output_hash == signed.signature.output_hash
    assert attestation.ree_receipt_hash == signed.response.ree_receipt_hash
    assert "receipt_status=validated" in attestation.reasons


def test_verifier_rejects_invalid_signature() -> None:
    signed = sign_agent_execution(
        task=_task(),
        response=_response(),
        identity=AgentIdentity(
            role="risk",
            peer_id="peer-risk-1",
            wallet=TEST_WALLET,
        ),
        private_key=TEST_PRIVATE_KEY,
    )
    tampered = SignedAgentExecution(
        task=signed.task,
        identity=signed.identity,
        response=signed.response.model_copy(update={"summary": "Tampered output."}),
        signature=signed.signature,
    )

    attestation = VerifierService().verify_signed_execution(tampered)

    assert attestation.status == "rejected"
    assert attestation.score == 0
    assert attestation.reasons == ["invalid_signature"]


def test_verifier_signs_attestation_when_key_is_configured() -> None:
    signed = sign_agent_execution(
        task=_task(),
        response=_response(),
        identity=AgentIdentity(
            role="risk",
            peer_id="peer-risk-1",
            wallet=TEST_WALLET,
        ),
        private_key=TEST_PRIVATE_KEY,
    )

    attestation = VerifierService(
        verifier_private_key=TEST_PRIVATE_KEY
    ).verify_signed_execution(signed)

    assert attestation.verifier == TEST_WALLET
    assert attestation.attestation_hash
    assert attestation.verifier_signature
    message = encode_defunct(
        primitive=canonical_json_bytes(
            {
                "domain": "signal-count.verifier-attestation",
                "attestation_hash": attestation.attestation_hash,
            }
        )
    )
    assert (
        Account.recover_message(message, signature=attestation.verifier_signature)
        == TEST_WALLET
    )
    assert verify_verification_attestation(attestation) is True


def test_verifier_applies_ree_policy() -> None:
    response_without_ree = _response().model_copy(
        update={"ree_receipt_hash": None, "receipt_status": None}
    )

    attestation = VerifierService(
        ree_policy="risk-only-ree",
        enforce_ree_policy=True,
    ).verify_response(task=_task(), response=response_without_ree)

    assert attestation.status == "rejected"
    assert attestation.score < 0.5
    assert "required_ree_missing:risk-only-ree" in attestation.reasons


def test_verifier_rejects_unsubstantiated_validated_receipt() -> None:
    response = _response().model_copy(update={"ree_receipt_body": {"not": "a receipt"}})

    attestation = VerifierService().verify_response(task=_task(), response=response)

    assert attestation.status == "rejected"
    assert "invalid_receipt_claim:receipt_body_invalid" in attestation.reasons


def test_verifier_rejects_verified_status_without_reexecution_evidence() -> None:
    response = _response().model_copy(update={"receipt_status": "verified"})

    attestation = VerifierService().verify_response(task=_task(), response=response)

    assert attestation.status == "rejected"
    assert (
        "invalid_receipt_claim:external_reexecution_evidence_missing"
        in attestation.reasons
    )


def test_verifier_rejects_parsed_status_without_embedded_material() -> None:
    response = _response().model_copy(
        update={"receipt_status": "parsed", "ree_receipt_body": None}
    )

    attestation = VerifierService().verify_response(task=_task(), response=response)

    assert attestation.status == "rejected"
    assert "invalid_receipt_claim:receipt_body_missing" in attestation.reasons
    assert "receipt_claim_gate=0.4900" in attestation.reasons


def _task() -> TaskSpec:
    return TaskSpec(
        job_id="job-verifier-1",
        thesis="ETH can outperform BTC if ETF flows accelerate.",
        asset="ETH",
        horizon_days=30,
    )


def _response() -> SpecialistResponse:
    receipt = json.loads(SYNTHETIC_RECEIPT.read_text(encoding="utf-8"))
    return SpecialistResponse(
        job_id="job-verifier-1",
        node_role="risk",
        peer_id="peer-risk-1",
        summary=(
            "ETH downside is underpriced if ETF flows stall, but invalidation is "
            "clear around support loss."
        ),
        scenario_view=ScenarioView(bull=0.25, base=0.45, bear=0.30),
        signals=["ETH options skew is elevated", "invalidation: support break"],
        risks=["ETF flow reversal", "macro volatility"],
        confidence=0.72,
        citations=["risk-note-1"],
        timestamp="2026-04-27T10:00:00Z",
        ree_receipt_hash=receipt["receipt_hash"],
        receipt_status="validated",
        ree_receipt_body=receipt,
    )
