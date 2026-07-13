"""Local REE receipt validation.

Validation binds the embedded prompt, canonical parameters, and text output to
supported SHA-256/Keccak component hashes, then recomputes the Gensyn master
commitment. Commit/config source bytes and non-content metadata are not present
to reconstruct locally. Only full external re-execution would prove that the
inference actually ran inside an REE.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from eth_utils import keccak

from app.identity.canonical import canonical_json_bytes
from app.ree.receipts import ReeReceipt, compute_receipt_hash


@dataclass(frozen=True)
class ReeValidationResult:
    """Outcome of a local REE receipt and content consistency check."""

    receipt_hash: str
    expected_receipt_hash: str
    expected_prompt_hash: str
    expected_parameters_hash: str
    expected_tokens_hash: str
    receipt_hash_matches: bool
    prompt_hash_matches: bool
    parameters_hash_matches: bool
    tokens_hash_matches: bool
    unsupported_component_hashes: tuple[str, ...] = ()

    @property
    def matches(self) -> bool:
        return all(
            (
                self.receipt_hash_matches,
                self.prompt_hash_matches,
                self.parameters_hash_matches,
                self.tokens_hash_matches,
                not self.unsupported_component_hashes,
            )
        )

    @property
    def is_valid(self) -> bool:
        return self.matches

    @property
    def failure_reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if not self.receipt_hash_matches:
            reasons.append("receipt_recomputation_failed")
        for component, matches in (
            ("prompt", self.prompt_hash_matches),
            ("parameters", self.parameters_hash_matches),
            ("tokens", self.tokens_hash_matches),
        ):
            if component in self.unsupported_component_hashes:
                reasons.append(f"{component}_hash_algorithm_unsupported")
            elif not matches:
                reasons.append(f"{component}_hash_mismatch")
        return tuple(reasons)


def validate_ree_receipt(receipt: ReeReceipt) -> ReeValidationResult:
    """Recompute content hashes and the master receipt commitment."""

    expected = compute_receipt_hash(
        commit_hash=receipt.commit_hash,
        config_hash=receipt.config_hash,
        prompt_hash=receipt.prompt_hash,
        parameters_hash=receipt.parameters_hash,
        tokens_hash=receipt.tokens_hash,
    )
    expected_prompt_hash = _content_hash(
        receipt.prompt.encode("utf-8"),
        declared=receipt.prompt_hash,
    )
    expected_parameters_hash = _content_hash(
        canonical_json_bytes(receipt.parameters),
        declared=receipt.parameters_hash,
    )
    expected_tokens_hash = _content_hash(
        receipt.text_output.encode("utf-8"),
        declared=receipt.tokens_hash,
    )
    unsupported = tuple(
        component
        for component, value in (
            ("prompt", expected_prompt_hash),
            ("parameters", expected_parameters_hash),
            ("tokens", expected_tokens_hash),
        )
        if value is None
    )
    return ReeValidationResult(
        receipt_hash=receipt.receipt_hash,
        expected_receipt_hash=expected,
        expected_prompt_hash=expected_prompt_hash or "",
        expected_parameters_hash=expected_parameters_hash or "",
        expected_tokens_hash=expected_tokens_hash or "",
        receipt_hash_matches=receipt.receipt_hash.lower() == expected.lower(),
        prompt_hash_matches=_hash_matches(receipt.prompt_hash, expected_prompt_hash),
        parameters_hash_matches=_hash_matches(
            receipt.parameters_hash,
            expected_parameters_hash,
        ),
        tokens_hash_matches=_hash_matches(receipt.tokens_hash, expected_tokens_hash),
        unsupported_component_hashes=unsupported,
    )


def _content_hash(value: bytes, *, declared: str) -> str | None:
    normalized = declared.strip().lower()
    if normalized.startswith("sha256:") and _has_hex_digest(
        normalized.removeprefix("sha256:")
    ):
        return f"sha256:{hashlib.sha256(value).hexdigest()}"
    if normalized.startswith("0x") and _has_hex_digest(normalized.removeprefix("0x")):
        return f"0x{keccak(value).hex()}"
    return None


def _has_hex_digest(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _hash_matches(declared: str, expected: str | None) -> bool:
    return expected is not None and declared.lower() == expected.lower()
