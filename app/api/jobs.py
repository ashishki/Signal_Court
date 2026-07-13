"""Public thesis-submission job routes."""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, HTTPException, Request, status

from app.chain.receipts import ChainReceipt, JobChainReceipts
from app.chain.verification import ChainTxVerification
from app.coordinator.service import CoordinatorDispatchResult
from app.evaluation.attestations import verify_verification_attestation
from app.identity.hashing import canonical_json_hash
from app.observability.provenance import NodeExecutionRecord
from app.ree.receipts import parse_ree_receipt
from app.ree.validator import validate_ree_receipt
from app.schemas.contracts import FinalMemo, ThesisRequest, VerificationAttestation
from app.store import JobStore


router = APIRouter()


class Coordinator(Protocol):
    async def dispatch(
        self,
        job_id: str,
        request: ThesisRequest,
    ) -> CoordinatorDispatchResult: ...


class MemoSynthesizer(Protocol):
    async def synthesize(
        self,
        job_id: str,
        request: ThesisRequest,
        dispatch_result: CoordinatorDispatchResult,
    ) -> FinalMemo: ...


class ChainReceiptRecorder(Protocol):
    async def record_job_receipts(
        self,
        *,
        job_id: str,
        request: ThesisRequest,
        dispatch_result: CoordinatorDispatchResult,
        memo: FinalMemo,
    ) -> JobChainReceipts: ...


class ChainTxVerifier(Protocol):
    def verify_transaction(self, tx_hash: str) -> ChainTxVerification: ...


def _get_job_store(request: Request) -> JobStore:
    return request.app.state.job_store  # type: ignore[no-any-return]


def _get_coordinator(request: Request) -> Coordinator:
    coordinator = getattr(request.app.state, "coordinator_service", None)
    if coordinator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Coordinator service is not configured.",
        )
    return coordinator  # type: ignore[no-any-return]


def _get_memo_synthesizer(request: Request) -> MemoSynthesizer:
    synthesizer = getattr(request.app.state, "memo_synthesis_service", None)
    if synthesizer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memo synthesis service is not configured.",
        )
    return synthesizer  # type: ignore[no-any-return]


def _get_chain_receipt_recorder(request: Request) -> ChainReceiptRecorder | None:
    return getattr(request.app.state, "chain_receipt_service", None)


def _get_chain_tx_verifier(request: Request) -> ChainTxVerifier | None:
    return getattr(request.app.state, "chain_tx_verifier", None)


async def create_completed_job_submission(
    *,
    payload: ThesisRequest,
    store: JobStore,
    coordinator: Coordinator,
    synthesizer: MemoSynthesizer,
    chain_receipt_recorder: ChainReceiptRecorder | None = None,
) -> dict[str, object]:
    job = await store.create_job(payload)
    dispatch_result = await coordinator.dispatch(job_id=job.job_id, request=payload)
    memo = await synthesizer.synthesize(
        job_id=job.job_id,
        request=payload,
        dispatch_result=dispatch_result,
    )
    run_metadata = dict(dispatch_result.run_metadata)
    run_metadata.update(
        await _build_chain_receipt_metadata(
            recorder=chain_receipt_recorder,
            job_id=job.job_id,
            request=payload,
            dispatch_result=dispatch_result,
            memo=memo,
        )
    )
    await store.complete_job(
        job_id=job.job_id,
        memo=memo,
        provenance_ledger=_build_provenance_ledger(
            dispatch_result.node_execution_records
        ),
        topology_snapshot=dispatch_result.topology_snapshot,
        run_metadata=run_metadata,
    )
    stored_job = await store.get_job(job.job_id)
    if stored_job is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Job could not be persisted.",
        )
    return {"job_id": stored_job.job_id, "status": stored_job.status}


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
async def create_job(payload: ThesisRequest, request: Request) -> dict[str, object]:
    store = _get_job_store(request)
    coordinator = _get_coordinator(request)
    synthesizer = _get_memo_synthesizer(request)
    return await create_completed_job_submission(
        payload=payload,
        store=store,
        coordinator=coordinator,
        synthesizer=synthesizer,
        chain_receipt_recorder=_get_chain_receipt_recorder(request),
    )


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict[str, object]:
    store = _get_job_store(request)
    job = await store.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )
    return job.to_dict()


@router.get("/jobs/{job_id}/verify")
async def verify_job(job_id: str, request: Request) -> dict[str, object]:
    store = _get_job_store(request)
    job = await store.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found."
        )
    return _build_job_verification_bundle(
        job.to_dict(),
        chain_tx_verifier=_get_chain_tx_verifier(request),
    )


@router.get("/reputation")
async def get_reputation_leaderboard(request: Request) -> dict[str, object]:
    store = _get_job_store(request)
    leaderboard = await store.get_reputation_leaderboard()
    return {"leaderboard": [entry.to_dict() for entry in leaderboard]}


def _build_provenance_ledger(
    node_execution_records: list[NodeExecutionRecord],
) -> list[dict[str, object]]:
    return [record.to_dict() for record in node_execution_records]


def _build_job_verification_bundle(
    job: dict[str, object],
    *,
    chain_tx_verifier: ChainTxVerifier | None = None,
) -> dict[str, object]:
    job_id = str(job.get("job_id", ""))
    run_metadata = _as_dict(job.get("run_metadata"))
    attestations = _as_dict_list(run_metadata.get("verification_attestations"))
    specialist_responses = _as_dict_list(run_metadata.get("specialist_responses"))
    chain_receipts = _as_dict_list(run_metadata.get("chain_receipts"))

    checks = {
        "output_hashes": _verify_output_hashes(
            attestations,
            specialist_responses,
            expected_job_id=job_id,
        ),
        "attestations": _verify_attestations(
            attestations,
            expected_job_id=job_id,
        ),
        "ree": _verify_ree_evidence(attestations, chain_receipts),
        "chain": _verify_chain_receipts(
            chain_receipts,
            chain_tx_verifier=chain_tx_verifier,
        ),
    }
    return {
        "job_id": job_id,
        "status": _rollup_status([check["status"] for check in checks.values()]),
        "checks": checks,
    }


def _verify_output_hashes(
    attestations: list[dict[str, object]],
    specialist_responses: list[dict[str, object]],
    *,
    expected_job_id: str,
) -> dict[str, object]:
    attestations_by_context: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    responses_by_context: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for attestation in attestations:
        attestations_by_context.setdefault(
            _verification_context(attestation), []
        ).append(attestation)
    for response in specialist_responses:
        responses_by_context.setdefault(_verification_context(response), []).append(
            response
        )

    items: list[dict[str, object]] = []
    all_contexts = sorted(attestations_by_context.keys() | responses_by_context.keys())
    for job_id, role, peer_id in all_contexts:
        matching_attestations = attestations_by_context.get((job_id, role, peer_id), [])
        matching_responses = responses_by_context.get((job_id, role, peer_id), [])
        item = {
            "job_id": job_id,
            "role": role,
            "peer_id": peer_id,
            "attestation_count": len(matching_attestations),
            "specialist_response_count": len(matching_responses),
        }
        if len(matching_attestations) == 1:
            item["output_hash"] = str(matching_attestations[0].get("output_hash", ""))
        if not job_id or not role or not peer_id:
            item.update(status="failed", reason="invalid_verification_context")
        elif job_id != expected_job_id:
            item.update(status="failed", reason="job_id_mismatch")
        elif len(matching_attestations) != 1:
            item.update(
                status="failed",
                reason=(
                    "missing_attestation"
                    if not matching_attestations
                    else "duplicate_attestation"
                ),
            )
        elif len(matching_responses) != 1:
            item.update(
                status="failed",
                reason=(
                    "missing_specialist_response"
                    if not matching_responses
                    else "duplicate_specialist_response"
                ),
            )
        else:
            output_hash = str(item["output_hash"])
            if not output_hash:
                item.update(status="missing", reason="missing_output_hash")
            else:
                recomputed = canonical_json_hash(matching_responses[0])
                item["recomputed_output_hash"] = recomputed
                item["status"] = "verified" if recomputed == output_hash else "failed"
                if recomputed != output_hash:
                    item["reason"] = "output_hash_mismatch"
        items.append(item)
    return {"status": _items_status(items), "items": items}


def _verification_context(item: dict[str, object]) -> tuple[str, str, str]:
    return (
        str(item.get("job_id", "")),
        str(item.get("node_role", "")),
        str(item.get("peer_id", "")),
    )


def _verify_attestations(
    attestations: list[dict[str, object]],
    *,
    expected_job_id: str,
) -> dict[str, object]:
    items = []
    for attestation in attestations:
        signature_status = _verify_attestation_signature(
            attestation,
            expected_job_id=expected_job_id,
        )
        items.append(
            {
                "role": str(attestation.get("node_role", "")),
                "status": signature_status,
                "attestation_hash": str(attestation.get("attestation_hash", "")),
                "verifier": str(attestation.get("verifier", "")),
            }
        )
    return {"status": _items_status(items), "items": items}


def _verify_attestation_signature(
    attestation: dict[str, object],
    *,
    expected_job_id: str,
) -> str:
    try:
        parsed = VerificationAttestation.model_validate(attestation)
    except Exception:
        return "failed"
    if parsed.job_id != expected_job_id:
        return "failed"
    attestation_hash = parsed.attestation_hash
    verifier = parsed.verifier
    signature = parsed.verifier_signature
    if not attestation_hash and not signature and not verifier:
        return "present"
    return "verified" if verify_verification_attestation(parsed) else "failed"


def _verify_ree_evidence(
    attestations: list[dict[str, object]],
    chain_receipts: list[dict[str, object]],
) -> dict[str, object]:
    evidence_by_role: dict[str, dict[str, object]] = {}
    for attestation in attestations:
        role = str(attestation.get("node_role", ""))
        if _has_ree_metadata(attestation):
            evidence_by_role[role] = _choose_ree_item(
                evidence_by_role.get(role),
                {
                    "role": role,
                    **_verify_ree_receipt_metadata(attestation),
                },
            )
    for receipt in chain_receipts:
        role = str(receipt.get("role", ""))
        if _has_ree_metadata(receipt):
            evidence_by_role[role] = _choose_ree_item(
                evidence_by_role.get(role),
                {
                    "role": role,
                    **_verify_ree_receipt_metadata(receipt),
                },
            )

    items = list(evidence_by_role.values())
    return {"status": _items_status(items), "items": items}


def _has_ree_metadata(item: dict[str, object]) -> bool:
    return bool(
        item.get("ree_receipt_hash")
        or item.get("receipt_status")
        or item.get("ree_status")
        or item.get("ree_receipt_body")
        or item.get("ree_receipt_path")
    )


def _verify_ree_receipt_metadata(item: dict[str, object]) -> dict[str, object]:
    declared_hash = str(item.get("ree_receipt_hash", ""))
    status_value = str(item.get("receipt_status") or item.get("ree_status") or "")
    source = item.get("ree_receipt_body") or item.get("ree_receipt_path")
    if source is None:
        return {
            "status": _ree_status(status_value),
            "receipt_hash": declared_hash,
        }

    try:
        receipt = parse_ree_receipt(source)  # type: ignore[arg-type]
        validation = validate_ree_receipt(receipt)
    except Exception:
        return {
            "status": "failed",
            "receipt_hash": declared_hash,
            "validation_source": _ree_validation_source(source),
            "error": "REE receipt could not be parsed for repeat validation",
        }

    hash_matches_metadata = (
        not declared_hash or receipt.receipt_hash.lower() == declared_hash.lower()
    )
    status = "validated" if validation.matches and hash_matches_metadata else "failed"
    payload: dict[str, object] = {
        "status": status,
        "receipt_hash": declared_hash or receipt.receipt_hash,
        "recomputed_receipt_hash": validation.expected_receipt_hash,
        "validation_source": _ree_validation_source(source),
    }
    if not validation.matches:
        payload["error"] = "REE receipt hash does not match recomputed hash"
    elif not hash_matches_metadata:
        payload["error"] = "REE receipt hash does not match stored metadata"
    return payload


def _ree_validation_source(source: object) -> str:
    return "body" if isinstance(source, dict) else "path"


def _choose_ree_item(
    current: dict[str, object] | None,
    candidate: dict[str, object],
) -> dict[str, object]:
    if current is None:
        return candidate
    return (
        candidate
        if _status_rank(str(candidate.get("status", "")))
        > _status_rank(str(current.get("status", "")))
        else current
    )


def _status_rank(status_value: str) -> int:
    status = status_value.strip().lower()
    if status == "failed":
        return 5
    if status == "verified":
        return 4
    if status == "validated":
        return 3
    if status == "present":
        return 2
    if status == "missing":
        return 1
    return 0


def _verify_chain_receipts(
    chain_receipts: list[dict[str, object]],
    *,
    chain_tx_verifier: ChainTxVerifier | None = None,
) -> dict[str, object]:
    items = []
    for receipt in chain_receipts:
        if not (receipt.get("tx_hash") or receipt.get("status")):
            continue
        tx_hash = str(receipt.get("tx_hash", ""))
        item = {
            "kind": str(receipt.get("kind", "")),
            "role": str(receipt.get("role", "")),
            "status": _chain_status(str(receipt.get("status", ""))),
            "tx_hash": tx_hash,
            "explorer_url": str(receipt.get("explorer_url", "")),
        }
        if receipt.get("rpc_status"):
            item["rpc_status"] = str(receipt.get("rpc_status", ""))
            if item["rpc_status"] == "confirmed":
                item["status"] = "verified"
        if chain_tx_verifier is not None and tx_hash:
            verification = chain_tx_verifier.verify_transaction(tx_hash)
            item.update(_chain_tx_verification_fields(verification))
        items.append(item)
    return {"status": _items_status(items), "items": items}


def _chain_tx_verification_fields(
    verification: ChainTxVerification,
) -> dict[str, object]:
    payload = verification.to_dict()
    payload.pop("tx_hash", None)
    return payload


def _ree_status(status_value: str) -> str:
    normalized = status_value.strip().lower().replace("_", "-")
    if normalized == "verified":
        return "verified"
    if normalized == "validated":
        return "validated"
    if normalized == "parsed":
        return "present"
    if normalized in {"failed", "error", "rejected"}:
        return "failed"
    return "present" if normalized else "missing"


def _chain_status(status_value: str) -> str:
    normalized = status_value.strip().lower().replace("_", "-")
    if normalized in {"confirmed", "recorded"}:
        return "present"
    if normalized in {"failed", "error", "rejected"}:
        return "failed"
    if normalized in {"pending", "submitted"}:
        return "present"
    return "missing"


def _items_status(items: list[dict[str, object]]) -> str:
    if not items:
        return "missing"
    return _rollup_status([str(item.get("status", "")) for item in items])


def _rollup_status(statuses: list[str]) -> str:
    normalized = [status.strip().lower() for status in statuses if status]
    if not normalized:
        return "missing"
    if "failed" in normalized:
        return "failed"
    if "missing" in normalized:
        return "missing"
    if normalized and all(status == "verified" for status in normalized):
        return "verified"
    if "validated" in normalized:
        return "validated"
    return "present"


def _as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _as_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


async def _build_chain_receipt_metadata(
    *,
    recorder: ChainReceiptRecorder | None,
    job_id: str,
    request: ThesisRequest,
    dispatch_result: CoordinatorDispatchResult,
    memo: FinalMemo,
) -> dict[str, object]:
    if recorder is None:
        return {}

    try:
        return (
            await recorder.record_job_receipts(
                job_id=job_id,
                request=request,
                dispatch_result=dispatch_result,
                memo=memo,
            )
        ).to_metadata()
    except Exception:
        return JobChainReceipts(
            receipt_status="failed",
            receipts=[
                ChainReceipt.failed(
                    kind="job_receipts",
                    error="chain receipt write failed",
                )
            ],
        ).to_metadata()
