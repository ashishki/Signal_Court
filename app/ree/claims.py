"""Fail-closed validation for REE receipt claims on specialist responses."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.ree.receipts import ReeReceipt, parse_ree_receipt
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
    receipt_hash_matches: bool | None = None
    prompt_hash_matches: bool | None = None
    parameters_hash_matches: bool | None = None
    tokens_hash_matches: bool | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def check_receipt_claim(response: SpecialistResponse) -> ReceiptClaimCheck:
    """Validate the material required by ``response.receipt_status``.

    ``validated`` is strictly a local consistency claim: an embedded REE body
    must parse; top-level metadata must match it; prompt, parameters, and text
    output must match supported component hashes; and the master commitment
    must recompute. ``verified`` is reserved for full external re-execution,
    which the current response schema cannot prove, so it fails closed.
    ``parsed`` requires structurally valid, cross-bound metadata without
    claiming successful local recomputation.
    """

    status = (response.receipt_status or "").strip().lower()
    declared_hash = response.ree_receipt_hash or ""
    if not status:
        if _has_receipt_material(response):
            return ReceiptClaimCheck(
                status="not_claimed",
                valid=False,
                reasons=("receipt_status_missing",),
                declared_hash=declared_hash,
            )
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
    receipt_hash_matches: bool | None = None
    prompt_hash_matches: bool | None = None
    parameters_hash_matches: bool | None = None
    tokens_hash_matches: bool | None = None
    receipt_body = response.ree_receipt_body

    if not declared_hash:
        reasons.append("receipt_hash_missing")

    if receipt_body is None:
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
            _check_embedded_metadata_bindings(
                response=response,
                receipt=receipt,
                reasons=reasons,
            )
            validation = validate_ree_receipt(receipt)
            recomputed_hash = validation.expected_receipt_hash
            receipt_hash_matches = validation.receipt_hash_matches
            prompt_hash_matches = validation.prompt_hash_matches
            parameters_hash_matches = validation.parameters_hash_matches
            tokens_hash_matches = validation.tokens_hash_matches
            if status in {"validated", "verified"}:
                reasons.extend(validation.failure_reasons)

    if status == "verified":
        reasons.append("external_reexecution_evidence_missing")

    return ReceiptClaimCheck(
        status=status,
        valid=not reasons,
        reasons=tuple(reasons),
        declared_hash=declared_hash,
        embedded_hash=embedded_hash,
        recomputed_hash=recomputed_hash,
        receipt_hash_matches=receipt_hash_matches,
        prompt_hash_matches=prompt_hash_matches,
        parameters_hash_matches=parameters_hash_matches,
        tokens_hash_matches=tokens_hash_matches,
    )


def _has_receipt_material(response: SpecialistResponse) -> bool:
    return any(
        value is not None and value != ""
        for value in (
            response.ree_receipt_hash,
            response.ree_prompt_hash,
            response.ree_tokens_hash,
            response.ree_model_name,
            response.ree_receipt_body,
            response.ree_receipt_path,
        )
    )


def _check_embedded_metadata_bindings(
    *,
    response: SpecialistResponse,
    receipt: ReeReceipt,
    reasons: list[str],
) -> None:
    for name, declared, embedded in (
        ("prompt_hash", response.ree_prompt_hash, receipt.prompt_hash),
        ("tokens_hash", response.ree_tokens_hash, receipt.tokens_hash),
        ("model_name", response.ree_model_name, receipt.model_name),
    ):
        if not declared:
            reasons.append(f"receipt_{name}_missing")
            continue
        if name.endswith("_hash"):
            matches = declared.lower() == embedded.lower()
        else:
            matches = declared == embedded
        if not matches:
            reasons.append(f"receipt_{name}_mismatch")
