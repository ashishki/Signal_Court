import json
from pathlib import Path

import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from app.evaluation.attestations import verify_verification_attestation
from app.evaluation.reputation import (
    build_reputation_leaderboard,
    build_reputation_updates,
)
from app.identity.canonical import canonical_json_bytes
from app.identity.signing import (
    _signable_message,
    output_hash,
    sign_agent_execution,
    task_hash,
    verify_signed_execution,
)
from app.nodes.verifier.service import VerifierService
from app.ree.receipts import parse_ree_receipt
from app.schemas.contracts import (
    AgentIdentity,
    ScenarioView,
    SignatureEnvelope,
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
    assert attestation.agent_wallet == TEST_WALLET
    assert attestation.output_hash == signed.signature.output_hash
    assert attestation.ree_receipt_hash == signed.response.ree_receipt_hash
    assert attestation.ree_receipt_body == parse_ree_receipt(
        signed.response.ree_receipt_body or {}
    ).model_dump(mode="json")
    assert "receipt_status=validated" in attestation.reasons
    update = build_reputation_updates([attestation])[0]
    assert update.agent_wallet == TEST_WALLET
    assert update.credit_eligible is True
    assert update.reputation_points > 0


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
    assert attestation.agent_wallet is None


def test_verifier_rejects_signed_wallet_substitution_without_credit() -> None:
    attacker_wallet = Account.from_key("0x" + "22" * 32).address
    task = _task()
    response = _response().model_copy(update={"agent_wallet": attacker_wallet})
    identity = AgentIdentity(
        role="risk",
        peer_id="peer-risk-1",
        wallet=TEST_WALLET,
    )
    task_digest = task_hash(task)
    output_digest = output_hash(response)
    signed_message = Account.sign_message(
        _signable_message(
            identity=identity,
            signer=TEST_WALLET,
            task_digest=task_digest,
            output_digest=output_digest,
        ),
        private_key=TEST_PRIVATE_KEY,
    )
    execution = SignedAgentExecution(
        task=task,
        identity=identity,
        response=response,
        signature=SignatureEnvelope(
            signer=TEST_WALLET,
            task_hash=task_digest,
            output_hash=output_digest,
            signature=f"0x{signed_message.signature.hex()}",
        ),
    )

    attestation = VerifierService().verify_signed_execution(execution)
    update = build_reputation_updates([attestation])[0]

    assert attestation.status == "rejected"
    assert attestation.agent_wallet is None
    assert update.agent_wallet is None
    assert update.credit_eligible is False
    assert update.verifier_score == 0
    assert update.reputation_points == 0


def test_unsigned_response_cannot_claim_wallet_credit() -> None:
    response = _response().model_copy(update={"agent_wallet": TEST_WALLET})

    attestation = VerifierService().verify_response(task=_task(), response=response)
    update = build_reputation_updates([attestation])[0]

    assert attestation.status == "accepted"
    assert attestation.signer is None
    assert attestation.agent_wallet is None
    assert update.agent_wallet is None
    assert update.credit_eligible is False
    assert update.verifier_score == 0
    assert update.reputation_points == 0
    assert build_reputation_leaderboard([update]) == []


def test_verifier_rejects_signed_job_id_mismatch_without_credit() -> None:
    task = _task()
    response = _response().model_copy(update={"job_id": "attacker-job"})
    identity = AgentIdentity(
        role="risk",
        peer_id="peer-risk-1",
        wallet=TEST_WALLET,
    )
    task_digest = task_hash(task)
    output_digest = output_hash(response)
    signed_message = Account.sign_message(
        _signable_message(
            identity=identity,
            signer=TEST_WALLET,
            task_digest=task_digest,
            output_digest=output_digest,
        ),
        private_key=TEST_PRIVATE_KEY,
    )
    execution = SignedAgentExecution(
        task=task,
        identity=identity,
        response=response,
        signature=SignatureEnvelope(
            signer=TEST_WALLET,
            task_hash=task_digest,
            output_hash=output_digest,
            signature=f"0x{signed_message.signature.hex()}",
        ),
    )

    assert verify_signed_execution(execution) is False
    attestation = VerifierService().verify_signed_execution(execution)
    update = build_reputation_updates([attestation])[0]

    assert attestation.job_id == task.job_id
    assert attestation.status == "rejected"
    assert attestation.reasons == ["task_response_job_id_mismatch"]
    assert update.credit_eligible is False
    assert update.reputation_points == 0


def test_verifier_rejects_unsigned_job_id_mismatch() -> None:
    response = _response().model_copy(update={"job_id": "attacker-job"})

    attestation = VerifierService().verify_response(task=_task(), response=response)

    assert attestation.job_id == _task().job_id
    assert attestation.status == "rejected"
    assert attestation.score == 0
    assert attestation.reasons == ["task_response_job_id_mismatch"]


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
        update={
            "ree_receipt_hash": None,
            "receipt_status": None,
            "ree_prompt_hash": None,
            "ree_tokens_hash": None,
            "ree_model_name": None,
            "ree_receipt_body": None,
        }
    )

    attestation = VerifierService(
        ree_policy="risk-only-ree",
        enforce_ree_policy=True,
    ).verify_response(task=_task(), response=response_without_ree)

    assert attestation.status == "rejected"
    assert attestation.score < 0.5
    assert "required_ree_missing:risk-only-ree" in attestation.reasons


def test_required_ree_policy_rejects_hash_without_status_or_body() -> None:
    response = _response().model_copy(
        update={
            "ree_receipt_hash": "attacker-controlled-nonempty",
            "receipt_status": None,
            "ree_prompt_hash": None,
            "ree_tokens_hash": None,
            "ree_model_name": None,
            "ree_receipt_body": None,
        }
    )

    attestation = VerifierService(
        ree_policy="risk-only-ree",
        enforce_ree_policy=True,
    ).verify_response(task=_task(), response=response)

    assert attestation.status == "rejected"
    assert "invalid_receipt_claim:receipt_status_missing" in attestation.reasons
    assert "required_ree_invalid:risk-only-ree" in attestation.reasons


def test_required_ree_policy_rejects_parsed_only_receipt() -> None:
    response = _response().model_copy(update={"receipt_status": "parsed"})

    attestation = VerifierService(
        ree_policy="risk-only-ree",
        enforce_ree_policy=True,
    ).verify_response(task=_task(), response=response)

    assert attestation.status == "rejected"
    assert "required_ree_not_validated:risk-only-ree" in attestation.reasons


def test_unknown_enforced_ree_policy_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsupported REE policy"):
        VerifierService(ree_policy="unknown-policy", enforce_ree_policy=True)


def test_verifier_rejects_unsubstantiated_validated_receipt() -> None:
    response = _response().model_copy(update={"ree_receipt_body": {"not": "a receipt"}})

    attestation = VerifierService().verify_response(task=_task(), response=response)

    assert attestation.status == "rejected"
    assert "invalid_receipt_claim:receipt_body_invalid" in attestation.reasons


def test_signed_receipt_unknown_claims_cannot_survive_attestation() -> None:
    receipt_body = dict(_response().ree_receipt_body or {})
    receipt_body.update(
        {
            "external_reexecution_evidence": {"status": "verified"},
            "production": True,
        }
    )
    response = _response().model_copy(update={"ree_receipt_body": receipt_body})
    signed = sign_agent_execution(
        task=_task(),
        response=response,
        identity=AgentIdentity(
            role="risk",
            peer_id="peer-risk-1",
            wallet=TEST_WALLET,
        ),
        private_key=TEST_PRIVATE_KEY,
    )

    assert verify_signed_execution(signed) is True
    attestation = VerifierService().verify_signed_execution(signed)
    serialized = attestation.model_dump_json()

    assert attestation.status == "rejected"
    assert "invalid_receipt_claim:receipt_body_invalid" in attestation.reasons
    assert attestation.ree_receipt_body is None
    assert "external_reexecution_evidence" not in serialized
    assert "production" not in serialized


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        (
            "ree_prompt_hash",
            "sha256:" + "00" * 32,
            "receipt_prompt_hash_mismatch",
        ),
        (
            "ree_tokens_hash",
            "sha256:" + "11" * 32,
            "receipt_tokens_hash_mismatch",
        ),
        ("ree_model_name", "attacker/model", "receipt_model_name_mismatch"),
    ),
)
def test_verifier_rejects_top_level_receipt_metadata_substitution(
    field: str,
    value: str,
    reason: str,
) -> None:
    response = _response().model_copy(update={field: value})

    attestation = VerifierService().verify_response(task=_task(), response=response)

    assert attestation.status == "rejected"
    assert f"invalid_receipt_claim:{reason}" in attestation.reasons


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    (
        ("prompt", "attacker-substituted prompt", "prompt_hash_mismatch"),
        (
            "parameters",
            {"max_new_tokens": 999},
            "parameters_hash_mismatch",
        ),
        ("text_output", "attacker-substituted output", "tokens_hash_mismatch"),
    ),
)
def test_verifier_rejects_embedded_receipt_content_substitution(
    field: str,
    value: object,
    reason: str,
) -> None:
    response = _response()
    receipt_body = dict(response.ree_receipt_body or {})
    receipt_body[field] = value
    response = response.model_copy(update={"ree_receipt_body": receipt_body})

    attestation = VerifierService().verify_response(task=_task(), response=response)

    assert attestation.status == "rejected"
    assert f"invalid_receipt_claim:{reason}" in attestation.reasons


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
        ree_prompt_hash=receipt["prompt_hash"],
        ree_tokens_hash=receipt["tokens_hash"],
        ree_model_name=receipt["model_name"],
        ree_receipt_body=receipt,
    )
