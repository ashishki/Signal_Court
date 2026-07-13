"""Verification attestation helpers."""

from __future__ import annotations

from eth_account import Account
from eth_account.messages import encode_defunct

from app.identity.canonical import canonical_json_bytes
from app.identity.hashing import canonical_json_hash
from app.schemas.contracts import VerificationAttestation

_SIGNATURE_FIELDS = {
    "verifier",
    "attestation_hash",
    "verifier_signature",
    "signature_algorithm",
}
VERIFIER_ATTESTATION_DOMAIN = "signal-count.verifier-attestation"


def verification_attestation_hash(attestation: VerificationAttestation) -> str:
    """Return a deterministic hash for recording a verifier verdict."""
    return canonical_json_hash(
        attestation.model_dump(mode="json", exclude=_SIGNATURE_FIELDS)
    )


def verification_attestation_message(attestation_hash: str):
    """Build the EIP-191 message used for a verifier verdict."""

    return encode_defunct(
        primitive=canonical_json_bytes(
            {
                "domain": VERIFIER_ATTESTATION_DOMAIN,
                "attestation_hash": attestation_hash,
            }
        )
    )


def verify_verification_attestation(attestation: VerificationAttestation) -> bool:
    """Return whether an attestation hash and EIP-191 signature are bound."""

    if (
        attestation.signature_algorithm != "eip191"
        or not attestation.verifier
        or not attestation.attestation_hash
        or not attestation.verifier_signature
    ):
        return False
    expected_hash = verification_attestation_hash(attestation)
    if expected_hash.lower() != attestation.attestation_hash.lower():
        return False
    try:
        recovered = Account.recover_message(
            verification_attestation_message(attestation.attestation_hash),
            signature=attestation.verifier_signature,
        )
    except Exception:
        return False
    return recovered.lower() == attestation.verifier.lower()
