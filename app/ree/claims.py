"""Fail-closed validation for REE receipt claims on specialist responses."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.ree.receipts import parse_ree_receipt
from app.ree.validator import validate_ree_receipt
from app.schemas.contracts import SpecialistResponse


@dataclass(frozen=True)
class ReceiptClaimCheck:
    """Result of checking the evidence behind one REE status claim."""

    status: str
    valid: bool
    reasons: tuple[str, ...]
    declared_hash: str = ""
    embedded_hash: str = ""
    recomputed_hash: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def check_receipt_claim(response: SpecialistResponse) -> ReceiptClaimCheck:
    """Validate the material required by ``response.receipt_status``.

    ``validated`` is strictly a local consistency claim: an embedded REE body
    must parse, its declared hash must match ``ree_receipt_hash``, and the hash
    must recompute under the supported REE algorithm. ``verified`` is reserved
    for full external re-execution, which the current response schema cannot
    prove, so it fails closed. ``parsed`` may carry a hash without proving a
    successful recomputation.
    """

    status = (response.receipt_status or "").strip().lower()
    declared_hash = response.ree_receipt_hash or ""
    if not status:
        return ReceiptClaimCheck(
            status="not_claimed",
            valid=True,
            reasons=(),
            declared_hash=declared_hash,
        )

    if status not in {"parsed", "validated", "verified"}:
        return ReceiptClaimCheck(
            status=status,
            valid=False,
            reasons=("unsupported_receipt_status",),
            declared_hash=declared_hash,
        )

    reasons: list[str] = []
    embedded_hash = ""
    recomputed_hash = ""
    receipt_body = response.ree_receipt_body

    if not declared_hash:
        reasons.append("receipt_hash_missing")

    if status in {"validated", "verified"} and receipt_body is None:
        reasons.append("receipt_body_missing")

    if receipt_body is not None:
        try:
            receipt = parse_ree_receipt(receipt_body)
        except (KeyError, OSError, TypeError, ValueError):
            reasons.append("receipt_body_invalid")
        else:
            embedded_hash = receipt.receipt_hash
            if declared_hash and declared_hash.lower() != embedded_hash.lower():
                reasons.append("receipt_hash_mismatch")
            validation = validate_ree_receipt(receipt)
            recomputed_hash = validation.expected_receipt_hash
            if status in {"validated", "verified"} and not validation.matches:
                reasons.append("receipt_recomputation_failed")

    if status == "verified":
        reasons.append("external_reexecution_evidence_missing")

    return ReceiptClaimCheck(
        status=status,
        valid=not reasons,
        reasons=tuple(reasons),
        declared_hash=declared_hash,
        embedded_hash=embedded_hash,
        recomputed_hash=recomputed_hash,
    )
