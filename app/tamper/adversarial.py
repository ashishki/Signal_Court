"""Demo tamper mutations for signed execution envelopes."""

from __future__ import annotations

from dataclasses import dataclass

from eth_account import Account

from app.identity.signing import sign_agent_execution
from app.schemas.contracts import (
    AgentIdentity,
    SignedAgentExecution,
)


@dataclass(frozen=True)
class Attack:
    name: str
    description: str
    expected_failed_checks: tuple[str, ...]


ATTACKS: tuple[Attack, ...] = (
    Attack(
        name="field_tamper_after_sign",
        description=(
            "Mutate response.summary after signing without resigning. The "
            "envelope output_hash no longer matches the body."
        ),
        expected_failed_checks=("output_hash_match",),
    ),
    Attack(
        name="signer_swap_in_envelope",
        description=(
            "Replace envelope.signer with a different address while keeping "
            "the original signature."
        ),
        expected_failed_checks=(
            "signer_equals_identity_wallet",
            "signature_recovers_signer",
        ),
    ),
    Attack(
        name="forged_signature_with_attacker_key",
        description=(
            "Re-sign the envelope with an attacker private key but keep the "
            "victim's identity.wallet."
        ),
        expected_failed_checks=("signature_recovers_signer",),
    ),
    Attack(
        name="agent_wallet_substitution",
        description=(
            "Replace response.agent_wallet with a different address while keeping "
            "the victim's signed identity."
        ),
        expected_failed_checks=(
            "output_hash_match",
            "response_wallet_matches_identity",
        ),
    ),
    Attack(
        name="role_substitution",
        description=(
            "Identity claims role=risk while response carries node_role=narrative."
        ),
        expected_failed_checks=("output_hash_match", "identity_role_match"),
    ),
    Attack(
        name="receipt_status_overclaim",
        description=(
            "Set receipt_status='verified' while stripping ree_receipt_body. "
            "Output hash also drifts because the response body changed."
        ),
        expected_failed_checks=("output_hash_match", "receipt_consistency"),
    ),
)


def field_tamper_after_sign(honest: SignedAgentExecution) -> SignedAgentExecution:
    tampered_response = honest.response.model_copy(
        update={"summary": honest.response.summary + " [TAMPERED PAYLOAD]"}
    )
    return honest.model_copy(update={"response": tampered_response})


def signer_swap_in_envelope(
    honest: SignedAgentExecution, attacker_address: str
) -> SignedAgentExecution:
    tampered_envelope = honest.signature.model_copy(update={"signer": attacker_address})
    return honest.model_copy(update={"signature": tampered_envelope})


def forged_signature_with_attacker_key(
    honest: SignedAgentExecution, attacker_private_key: str
) -> SignedAgentExecution:
    attacker_address = Account.from_key(attacker_private_key).address
    spoof_identity = AgentIdentity(
        role=honest.identity.role,
        peer_id=honest.identity.peer_id,
        wallet=attacker_address,
    )
    spoof_response = honest.response.model_copy(
        update={"agent_wallet": attacker_address}
    )
    resigned = sign_agent_execution(
        task=honest.task,
        response=spoof_response,
        identity=spoof_identity,
        private_key=attacker_private_key,
    )
    forged_envelope = resigned.signature.model_copy(
        update={
            "signer": honest.identity.wallet,
            "output_hash": honest.signature.output_hash,
        }
    )
    return honest.model_copy(update={"signature": forged_envelope})


def agent_wallet_substitution(
    honest: SignedAgentExecution,
    attacker_address: str,
) -> SignedAgentExecution:
    tampered_response = honest.response.model_copy(
        update={"agent_wallet": attacker_address}
    )
    return honest.model_copy(update={"response": tampered_response})


def role_substitution(honest: SignedAgentExecution) -> SignedAgentExecution:
    other_role = "narrative" if honest.identity.role != "narrative" else "risk"
    tampered_response = honest.response.model_copy(update={"node_role": other_role})
    return honest.model_copy(update={"response": tampered_response})


def receipt_status_overclaim(honest: SignedAgentExecution) -> SignedAgentExecution:
    tampered_response = honest.response.model_copy(
        update={
            "receipt_status": "verified",
            "ree_receipt_body": None,
            "ree_receipt_hash": None,
            "ree_receipt_path": None,
        }
    )
    return honest.model_copy(update={"response": tampered_response})


ATTACK_FUNCTIONS = {
    "field_tamper_after_sign": field_tamper_after_sign,
    "signer_swap_in_envelope": signer_swap_in_envelope,
    "forged_signature_with_attacker_key": forged_signature_with_attacker_key,
    "agent_wallet_substitution": agent_wallet_substitution,
    "role_substitution": role_substitution,
    "receipt_status_overclaim": receipt_status_overclaim,
}
