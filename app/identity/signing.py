"""Signing helpers for specialist execution envelopes."""

from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import to_checksum_address

from app.identity.canonical import canonical_json_bytes
from app.identity.hashing import canonical_json_hash
from app.schemas.contracts import (
    AgentIdentity,
    SignatureEnvelope,
    SignedAgentExecution,
    SpecialistResponse,
    TaskSpec,
)

SIGNATURE_DOMAIN = "signal-count.agent-execution"
SIGNATURE_VERSION = 1


def wallet_address_from_private_key(private_key: str) -> str:
    """Derive a checksummed Ethereum address from a private key."""
    return Account.from_key(private_key).address


def task_hash(task: TaskSpec) -> str:
    """Return the canonical task hash bound into agent signatures."""
    return canonical_json_hash(task)


def output_hash(response: SpecialistResponse) -> str:
    """Return the canonical specialist output hash bound into signatures."""
    return canonical_json_hash(response)


def sign_agent_execution(
    *,
    task: TaskSpec,
    response: SpecialistResponse,
    identity: AgentIdentity,
    private_key: str,
) -> SignedAgentExecution:
    """Sign an execution envelope with an Ethereum account private key."""
    signer = wallet_address_from_private_key(private_key)
    normalized_identity = _normalize_identity(identity)

    if signer.lower() != normalized_identity.wallet.lower():
        raise ValueError("private key does not match agent identity wallet")
    if task.job_id != response.job_id:
        raise ValueError("task job_id does not match specialist response")
    if response.node_role != normalized_identity.role:
        raise ValueError("agent identity role does not match specialist response")
    if response.peer_id != normalized_identity.peer_id:
        raise ValueError("agent identity peer_id does not match specialist response")
    if not _response_wallet_matches_identity(response, normalized_identity):
        raise ValueError("specialist response wallet does not match agent identity")

    task_digest = task_hash(task)
    output_digest = output_hash(response)
    message = _signable_message(
        identity=normalized_identity,
        signer=signer,
        task_digest=task_digest,
        output_digest=output_digest,
    )
    signed_message = Account.sign_message(message, private_key=private_key)
    envelope = SignatureEnvelope(
        signer=signer,
        task_hash=task_digest,
        output_hash=output_digest,
        signature=f"0x{signed_message.signature.hex()}",
    )

    return SignedAgentExecution(
        task=task,
        identity=normalized_identity,
        response=response,
        signature=envelope,
    )


def recover_execution_signer(signed_execution: SignedAgentExecution) -> str:
    """Recover the checksummed signer address from a signed execution."""
    envelope = signed_execution.signature
    message = _signable_message(
        identity=_normalize_identity(signed_execution.identity),
        signer=to_checksum_address(envelope.signer),
        task_digest=envelope.task_hash,
        output_digest=envelope.output_hash,
    )
    recovered = Account.recover_message(message, signature=envelope.signature)
    return to_checksum_address(recovered)


def verify_signed_execution(signed_execution: SignedAgentExecution) -> bool:
    """Return whether hashes and signature match the wrapped execution."""
    envelope = signed_execution.signature
    identity = _normalize_identity(signed_execution.identity)
    response = signed_execution.response

    if envelope.algorithm != "eip191":
        return False
    if signed_execution.task.job_id != response.job_id:
        return False
    if response.node_role != identity.role or response.peer_id != identity.peer_id:
        return False
    if envelope.signer.lower() != identity.wallet.lower():
        return False
    if not _response_wallet_matches_identity(response, identity):
        return False
    if envelope.task_hash != task_hash(signed_execution.task):
        return False
    if envelope.output_hash != output_hash(response):
        return False

    try:
        recovered = recover_execution_signer(signed_execution)
    except Exception:
        return False
    return recovered.lower() == envelope.signer.lower()


def _normalize_identity(identity: AgentIdentity) -> AgentIdentity:
    return identity.model_copy(update={"wallet": to_checksum_address(identity.wallet)})


def _response_wallet_matches_identity(
    response: SpecialistResponse,
    identity: AgentIdentity,
) -> bool:
    if response.agent_wallet is None:
        return True
    return to_checksum_address(response.agent_wallet) == to_checksum_address(
        identity.wallet
    )


def _signable_message(
    *,
    identity: AgentIdentity,
    signer: str,
    task_digest: str,
    output_digest: str,
):
    payload = {
        "domain": SIGNATURE_DOMAIN,
        "version": SIGNATURE_VERSION,
        "role": identity.role,
        "peer_id": identity.peer_id,
        "wallet": to_checksum_address(signer),
        "task_hash": task_digest,
        "output_hash": output_digest,
    }
    return encode_defunct(primitive=canonical_json_bytes(payload))
