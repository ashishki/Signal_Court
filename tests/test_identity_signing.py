import pytest
from eth_account import Account

from app.identity.hashing import canonical_json_hash
from app.identity.signing import (
    _signable_message,
    output_hash,
    recover_execution_signer,
    sign_agent_execution,
    task_hash,
    verify_signed_execution,
    wallet_address_from_private_key,
)
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


def test_signed_execution_recovers_signer() -> None:
    task = _task()
    response = _response()
    identity = AgentIdentity(
        role="risk",
        peer_id="peer-risk-1",
        wallet=wallet_address_from_private_key(TEST_PRIVATE_KEY),
    )

    signed = sign_agent_execution(
        task=task,
        response=response,
        identity=identity,
        private_key=TEST_PRIVATE_KEY,
    )

    assert signed.signature.task_hash == canonical_json_hash(task)
    assert signed.signature.output_hash == canonical_json_hash(response)
    assert signed.signature.signer == TEST_WALLET
    assert recover_execution_signer(signed) == TEST_WALLET
    assert verify_signed_execution(signed) is True


def test_tampered_execution_fails_verification() -> None:
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
    tampered_response = signed.response.model_copy(
        update={"summary": "A different conclusion was inserted after signing."}
    )
    tampered = SignedAgentExecution(
        task=signed.task,
        identity=signed.identity,
        response=tampered_response,
        signature=signed.signature,
    )

    assert verify_signed_execution(tampered) is False


def test_signature_binds_task_hash_and_output_hash() -> None:
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
    tampered_task = signed.task.model_copy(update={"horizon_days": 45})
    tampered = SignedAgentExecution(
        task=tampered_task,
        identity=signed.identity,
        response=signed.response,
        signature=signed.signature,
    )

    assert verify_signed_execution(tampered) is False


def test_signer_rejects_task_response_job_id_mismatch() -> None:
    with pytest.raises(ValueError, match="task job_id"):
        sign_agent_execution(
            task=_task(),
            response=_response().model_copy(update={"job_id": "attacker-job"}),
            identity=AgentIdentity(
                role="risk",
                peer_id="peer-risk-1",
                wallet=TEST_WALLET,
            ),
            private_key=TEST_PRIVATE_KEY,
        )


def test_fully_signed_job_id_substitution_fails_verification() -> None:
    task = _task()
    response = _response().model_copy(update={"job_id": "attacker-job"})
    identity = AgentIdentity(
        role="risk",
        peer_id="peer-risk-1",
        wallet=TEST_WALLET,
    )
    task_digest = task_hash(task)
    output_digest = output_hash(response)
    message = _signable_message(
        identity=identity,
        signer=TEST_WALLET,
        task_digest=task_digest,
        output_digest=output_digest,
    )
    signature = Account.sign_message(message, private_key=TEST_PRIVATE_KEY)
    execution = SignedAgentExecution(
        task=task,
        identity=identity,
        response=response,
        signature=SignatureEnvelope(
            signer=TEST_WALLET,
            task_hash=task_digest,
            output_hash=output_digest,
            signature=f"0x{signature.signature.hex()}",
        ),
    )

    assert recover_execution_signer(execution) == TEST_WALLET
    assert verify_signed_execution(execution) is False


def test_signer_cannot_attribute_execution_to_a_different_response_wallet() -> None:
    attacker_wallet = Account.from_key("0x" + "22" * 32).address
    response = _response().model_copy(update={"agent_wallet": attacker_wallet})
    identity = AgentIdentity(
        role="risk",
        peer_id="peer-risk-1",
        wallet=TEST_WALLET,
    )

    with pytest.raises(ValueError, match="response wallet"):
        sign_agent_execution(
            task=_task(),
            response=response,
            identity=identity,
            private_key=TEST_PRIVATE_KEY,
        )


def test_fully_signed_wallet_substitution_fails_verification() -> None:
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
    message = _signable_message(
        identity=identity,
        signer=TEST_WALLET,
        task_digest=task_digest,
        output_digest=output_digest,
    )
    signature = Account.sign_message(message, private_key=TEST_PRIVATE_KEY)
    execution = SignedAgentExecution(
        task=task,
        identity=identity,
        response=response,
        signature=SignatureEnvelope(
            signer=TEST_WALLET,
            task_hash=task_digest,
            output_hash=output_digest,
            signature=f"0x{signature.signature.hex()}",
        ),
    )

    assert recover_execution_signer(execution) == TEST_WALLET
    assert verify_signed_execution(execution) is False


def _task() -> TaskSpec:
    return TaskSpec(
        job_id="job-123",
        thesis="ETH can outperform BTC over the next 30 days.",
        asset="ETH",
        horizon_days=30,
    )


def _response() -> SpecialistResponse:
    return SpecialistResponse(
        job_id="job-123",
        node_role="risk",
        peer_id="peer-risk-1",
        summary="Downside is underpriced if ETF flows stall.",
        scenario_view=ScenarioView(bull=0.25, base=0.45, bear=0.30),
        signals=["options skew is elevated"],
        risks=["flow reversal"],
        confidence=0.66,
        citations=["risk-note-1"],
        timestamp="2026-04-27T10:00:00Z",
    )
