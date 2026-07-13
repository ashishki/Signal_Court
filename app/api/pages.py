"""Operator-facing demo pages."""

from __future__ import annotations

from html import escape
from pathlib import Path
from string import Template
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from app.api.jobs import (
    _build_job_verification_bundle,
    create_completed_job_submission,
)
from app.demo.fixtures import DemoFixture, get_demo_fixture, list_demo_fixtures
from app.indexer.projections import ChainEventsProjection
from app.rendering.memo import render_memo_html
from app.schemas.contracts import FinalMemo, ThesisRequest
from app.store import JobRecord, JobStore


router = APIRouter()
_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "index.html"


def _get_job_store(request: Request) -> JobStore:
    return request.app.state.job_store  # type: ignore[no-any-return]


def _get_coordinator(request: Request):
    coordinator = getattr(request.app.state, "coordinator_service", None)
    if coordinator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Coordinator service is not configured.",
        )
    return coordinator


def _get_memo_synthesizer(request: Request):
    synthesizer = getattr(request.app.state, "memo_synthesis_service", None)
    if synthesizer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Memo synthesis service is not configured.",
        )
    return synthesizer


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request) -> HTMLResponse:
    store = _get_job_store(request)
    latest_job = await store.get_latest_job()
    indexed_projection = await store.get_indexed_chain_projection()
    template = Template(_TEMPLATE_PATH.read_text())
    html = template.safe_substitute(
        fixture_cards=_render_fixture_cards(),
        capability_strip=_render_capability_strip(latest_job, indexed_projection),
        latest_job_panel=_render_latest_job_panel(latest_job, indexed_projection),
    )
    return HTMLResponse(content=html)


@router.post("/demo/submit")
async def submit_demo_job(
    request: Request,
) -> RedirectResponse:
    form = await _parse_urlencoded_body(request)
    await create_completed_job_submission(
        payload=_build_thesis_request(form),
        store=_get_job_store(request),
        coordinator=_get_coordinator(request),
        synthesizer=_get_memo_synthesizer(request),
    )
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/demo/replay/{fixture_id}")
async def replay_demo_fixture(
    fixture_id: str,
    request: Request,
) -> RedirectResponse:
    try:
        fixture = get_demo_fixture(fixture_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    await create_completed_job_submission(
        payload=_fixture_to_request(fixture),
        store=_get_job_store(request),
        coordinator=_get_coordinator(request),
        synthesizer=_get_memo_synthesizer(request),
    )
    return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)


def _render_fixture_cards() -> str:
    cards: list[str] = []
    role_classes = ("regime", "narrative", "risk")
    for index, fixture in enumerate(list_demo_fixtures()):
        role_class = role_classes[index % len(role_classes)]
        cards.append(
            "\n".join(
                [
                    f'<article class="fixture-card agent-card {role_class} done">',
                    '<div class="card-header">',
                    "<div>",
                    f'<div class="agent-name">{escape(fixture.title)}</div>',
                    '<div class="agent-role">Replayable market thesis fixture</div>',
                    "</div>",
                    '<div class="status-ring" aria-hidden="true">ok</div>',
                    "</div>",
                    f"<p>{escape(fixture.thesis)}</p>",
                    '<dl class="fixture-meta">',
                    f"<div><dt>Asset</dt><dd>{escape(fixture.asset)}</dd></div>",
                    (
                        "<div><dt>Horizon</dt><dd>"
                        f"{fixture.horizon_days} days</dd></div>"
                    ),
                    "</dl>",
                    f'<form action="/demo/replay/{escape(fixture.fixture_id)}" method="post">',
                    '<button type="submit">Replay Fixture</button>',
                    "</form>",
                    "</article>",
                ]
            )
        )
    return "\n".join(cards)


def _render_capability_strip(
    latest_job: JobRecord | None,
    indexed_projection: ChainEventsProjection,
) -> str:
    run_metadata = latest_job.run_metadata if latest_job is not None else {}
    mode = str(run_metadata.get("run_mode") or "no-run")
    transport = str(run_metadata.get("transport") or "")
    return "\n".join(
        [
            '<section class="capability-strip" aria-label="Proof capabilities">',
            _render_capability("Mode", mode, _status_for_mode(mode)),
            _render_capability(
                "AXL",
                transport or "not recorded",
                "confirmed" if transport == "axl-mcp" else "missing",
            ),
            _render_capability(
                "REE",
                "receipt present" if _has_ree_evidence(run_metadata) else "not present",
                "confirmed" if _has_ree_evidence(run_metadata) else "missing",
            ),
            _render_capability(
                "Chain",
                str(run_metadata.get("receipt_status") or "not configured"),
                _status_for_receipts(run_metadata),
            ),
            _render_capability(
                "Indexer",
                f"{len(indexed_projection.contributions)} contributions indexed",
                "confirmed" if indexed_projection.contributions else "missing",
            ),
            "</section>",
        ]
    )


def _render_capability(label: str, value: str, status: str) -> str:
    return (
        f'<div class="capability cap-chip capability-{escape(status)}">'
        f"<span>{escape(label)}</span>"
        f"<strong>{escape(value)}</strong>"
        "</div>"
    )


def _render_latest_job_panel(
    latest_job: JobRecord | None,
    indexed_projection: ChainEventsProjection,
) -> str:
    if latest_job is None or latest_job.memo is None:
        return (
            '<section class="job-panel empty">'
            "<h2>Latest Job</h2>"
            "<p>No completed jobs yet. Submit a thesis to generate the first memo.</p>"
            "</section>"
        )

    memo_html = render_memo_html(FinalMemo.model_validate(latest_job.memo))
    thesis = escape(str(latest_job.payload.get("thesis", "")))
    asset = escape(str(latest_job.payload.get("asset", "")))
    horizon_days = escape(str(latest_job.payload.get("horizon_days", "")))

    return "\n".join(
        [
            '<section class="job-panel">',
            '<div class="job-panel-topbar">',
            '<div class="job-id-group">',
            '<span class="job-id-label">Latest Job</span>',
            f'<span class="job-id-val">Job ID: <code>{escape(latest_job.job_id)}</code></span>',
            "</div>",
            '<div class="job-id-group">',
            (f'<span class="job-meta">{asset} / {horizon_days} days</span>'),
            (
                f'<span class="status-pill status status-{escape(_status_class(latest_job.status))}">'
                f"{escape(latest_job.status)}</span>"
            ),
            "</div>",
            "</div>",
            '<div class="tab-bar">',
            '<button class="tab-btn active" type="button" onclick="switchTab(\'ledger\', this)">Verify Run</button>',
            '<button class="tab-btn" type="button" onclick="switchTab(\'memo\', this)">Risk Memo</button>',
            '<button class="tab-btn" type="button" onclick="switchTab(\'timeline\', this)">Run Timeline</button>',
            "</div>",
            '<div class="tab-pane" id="tab-timeline">',
            '<div class="job-request">',
            "<h3>Submitted Thesis</h3>",
            f"<p>{thesis}</p>",
            (
                '<p class="job-meta">'
                f"Asset: <strong>{asset}</strong> "
                f"&middot; Horizon: <strong>{horizon_days} days</strong></p>"
            ),
            "</div>",
            _render_run_timeline(latest_job.provenance_ledger, latest_job.run_metadata),
            "</div>",
            '<div class="tab-pane" id="tab-memo">',
            '<div class="job-memo">',
            memo_html,
            "</div>",
            "</div>",
            '<div class="tab-pane active" id="tab-ledger">',
            '<section class="proof-console-layout">',
            '<div class="proof-column primary-proof">',
            _render_trace_ledger(
                latest_job.provenance_ledger,
                latest_job.run_metadata,
            ),
            _render_verification_panel(latest_job),
            _render_risk_ree_hero(latest_job.run_metadata),
            _render_proof_details(latest_job.run_metadata),
            "</div>",
            '<div class="proof-column support-proof">',
            _render_agent_registry(
                latest_job.provenance_ledger, latest_job.run_metadata
            ),
            _render_reputation_panel(latest_job.run_metadata, indexed_projection),
            _render_indexed_events_panel(indexed_projection),
            "</div>",
            "</section>",
            _render_run_metadata(latest_job.run_metadata),
            '<section class="node-participation">',
            "<h3>Run Evidence</h3>",
            '<table class="ledger-table">',
            (
                "<thead><tr><th>Role</th><th>Peer</th><th>Service</th>"
                "<th>Transport</th><th>Status</th><th>Latency (ms)</th>"
                "<th>Selection</th><th>Attempts</th>"
                "<th>Dispatch target</th></tr></thead>"
            ),
            f"<tbody>{_render_node_rows(latest_job.provenance_ledger)}</tbody>",
            "</table>",
            "</section>",
            _render_topology(latest_job.topology_snapshot),
            "</div>",
            "</section>",
        ]
    )


def _render_run_timeline(
    provenance_ledger: list[dict[str, object]],
    run_metadata: dict[str, object],
) -> str:
    items = [
        ("Task Created", str(run_metadata.get("receipt_status") or "recorded")),
        ("Specialists", _roles_status(provenance_ledger)),
        ("Verifier", _verification_status(run_metadata)),
        (
            "REE Receipt",
            "present" if _has_ree_evidence(run_metadata) else "not present",
        ),
        ("Chain Receipt", str(run_metadata.get("receipt_status") or "not configured")),
        ("Final Memo", "rendered"),
    ]
    rendered = "".join(
        (
            f'<li class="timeline-step status-border-{escape(_status_class(status))}">'
            f"<span>{escape(label)}</span>"
            f'<strong class="status status-{escape(_status_class(status))}">'
            f"{escape(status)}</strong>"
            "</li>"
        )
        for label, status in items
    )
    return (
        '<section class="run-timeline">'
        "<h3>Run Timeline</h3>"
        f"<ol>{rendered}</ol>"
        "</section>"
    )


def _render_trace_ledger(
    provenance_ledger: list[dict[str, object]],
    run_metadata: dict[str, object],
) -> str:
    rows = _render_trace_rows(provenance_ledger, run_metadata)
    if not rows:
        rows = '<tr><td colspan="7">No trace evidence recorded for this job.</td></tr>'
    return "\n".join(
        [
            '<section class="trace-ledger">',
            "<h3>Task Trace</h3>",
            '<table class="ledger-table trace-table">',
            (
                "<thead><tr><th>Role</th><th>AXL Peer</th><th>Wallet</th>"
                "<th>Output Hash</th><th>REE Receipt</th><th>Status</th>"
                "<th>Tx</th></tr></thead>"
            ),
            f"<tbody>{rows}</tbody>",
            "</table>",
            "</section>",
        ]
    )


def _render_trace_rows(
    provenance_ledger: list[dict[str, object]],
    run_metadata: dict[str, object],
) -> str:
    attestations = _by_role(run_metadata.get("verification_attestations"))
    contribution_receipts = _chain_receipts_by_role(
        run_metadata.get("chain_receipts"),
        kind="contribution",
    )
    reputation_receipts = _chain_receipts_by_role(
        run_metadata.get("chain_receipts"),
        kind="reputation",
    )

    rows: list[str] = []
    for record in provenance_ledger:
        role = str(record.get("node_role", ""))
        attestation = attestations.get(role, {})
        contribution_receipt = contribution_receipts.get(role, {})
        reputation_receipt = reputation_receipts.get(role, {})
        receipt = contribution_receipt or reputation_receipt
        status = (
            receipt.get("status")
            or attestation.get("status")
            or record.get("status")
            or ""
        )
        rows.append(
            "<tr>"
            f"<td>{escape(role)}</td>"
            f"<td>{_render_compact_id(record.get('peer_id'))}</td>"
            f"<td>{_render_compact_id(attestation.get('agent_wallet'))}</td>"
            f'<td><code class="hash-chip" title="{escape(str(attestation.get("output_hash", "")))}">{escape(_short(str(attestation.get("output_hash", ""))))}</code></td>'
            f"<td>{_render_ree_cell(attestation, contribution_receipt)}</td>"
            f'<td><span class="status status-{escape(_status_class(str(status)))}">{escape(str(status))}</span></td>'
            f"<td>{_render_tx_cell(receipt)}</td>"
            "</tr>"
        )
    return "".join(rows)


def _render_verification_panel(latest_job: JobRecord) -> str:
    bundle = _build_job_verification_bundle(latest_job.to_dict())
    checks = bundle.get("checks", {})
    rows: list[str] = []
    if isinstance(checks, dict):
        for label in ("output_hashes", "attestations", "ree", "chain"):
            check = checks.get(label)
            if not isinstance(check, dict):
                continue
            check_status = str(check.get("status", "missing"))
            rows.append(
                "<tr>"
                f"<td>{escape(label)}</td>"
                f'<td><span class="status status-{escape(_status_class(check_status))}">{escape(check_status)}</span></td>'
                f"<td>{escape(str(len(check.get('items', [])) if isinstance(check.get('items'), list) else 0))}</td>"
                f"<td>{escape(_verification_evidence_label(label, check))}</td>"
                "</tr>"
            )
    if not rows:
        rows.append('<tr><td colspan="4">No verification checks available.</td></tr>')
    status_value = str(bundle.get("status", "missing"))
    return (
        '<section class="verification-panel">'
        "<h3>Verify Run</h3>"
        '<div class="job-id-group">'
        f'<span class="status status-{escape(_status_class(status_value))}">{escape(status_value)}</span>'
        f'<a class="hash-chip" href="/jobs/{escape(latest_job.job_id)}/verify">open proof bundle</a>'
        "</div>"
        '<table class="ledger-table compact-table">'
        "<thead><tr><th>Check</th><th>Status</th><th>Items</th><th>Evidence</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</section>"
    )


def _verification_evidence_label(label: str, check: dict[str, object]) -> str:
    items = check.get("items")
    item_list = (
        [item for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else []
    )
    if not item_list:
        return "missing"
    if label == "output_hashes":
        recomputed_count = sum(
            1 for item in item_list if item.get("recomputed_output_hash")
        )
        if recomputed_count == len(item_list):
            return "verified from stored specialist payload"
        if recomputed_count:
            return "mixed: stored payload and present only"
        return "present only"
    if label == "ree":
        source_count = sum(1 for item in item_list if item.get("validation_source"))
        sources = {
            str(item.get("validation_source", ""))
            for item in item_list
            if item.get("validation_source")
        }
        if source_count == len(item_list):
            return "validated from receipt " + "/".join(sorted(sources))
        if source_count:
            return "mixed: receipt material and present only"
        return "present only"
    if label == "chain":
        rpc_count = sum(1 for item in item_list if item.get("rpc_status"))
        confirmed_count = sum(
            1 for item in item_list if item.get("rpc_status") == "confirmed"
        )
        if confirmed_count == len(item_list):
            return "verified by RPC"
        if rpc_count:
            return "checked by RPC"
        return "present only"
    if label == "attestations":
        if str(check.get("status")) == "verified":
            return "verified signature"
        return "present only"
    return "present only"


def _render_risk_ree_hero(run_metadata: dict[str, object]) -> str:
    attestations = _by_role(run_metadata.get("verification_attestations"))
    risk_attestation = attestations.get("risk", {})
    contribution_receipt = _chain_receipts_by_role(
        run_metadata.get("chain_receipts"),
        kind="contribution",
    ).get("risk", {})
    values = [
        ("model", risk_attestation.get("ree_model_name")),
        ("prompt_hash", risk_attestation.get("ree_prompt_hash")),
        ("tokens_hash", risk_attestation.get("ree_tokens_hash")),
        (
            "receipt_hash",
            contribution_receipt.get("ree_receipt_hash")
            or risk_attestation.get("ree_receipt_hash"),
        ),
        ("output_hash", risk_attestation.get("output_hash")),
        ("tx", contribution_receipt.get("tx_hash")),
    ]
    rows = "".join(
        "<tr>"
        f"<th>{escape(label)}</th>"
        f'<td><code class="hash-chip">{escape(str(value))}</code></td>'
        "</tr>"
        for label, value in values
        if value
    )
    status_value = str(
        contribution_receipt.get("ree_status")
        or risk_attestation.get("receipt_status")
        or "missing"
    )
    if not rows:
        rows = '<tr><td colspan="2">No risk REE proof metadata recorded.</td></tr>'
    return (
        '<section class="risk-ree-proof">'
        "<h3>Risk REE Proof</h3>"
        f'<span class="status status-{escape(_status_class(status_value))}">{escape(status_value)}</span>'
        '<table class="ledger-table compact-table">'
        f"<tbody>{rows}</tbody>"
        "</table>"
        "</section>"
    )


def _by_role(value: object) -> dict[str, dict[str, object]]:
    if not isinstance(value, list):
        return {}
    return {
        str(item.get("node_role")): item
        for item in value
        if isinstance(item, dict) and item.get("node_role")
    }


def _chain_receipts_by_role(
    value: object,
    *,
    kind: str,
) -> dict[str, dict[str, object]]:
    if not isinstance(value, list):
        return {}
    return {
        str(item.get("role")): item
        for item in value
        if isinstance(item, dict) and item.get("kind") == kind and item.get("role")
    }


def _render_ree_cell(
    attestation: dict[str, object],
    receipt: dict[str, object],
) -> str:
    ree_hash = receipt.get("ree_receipt_hash") or attestation.get("ree_receipt_hash")
    ree_status = receipt.get("ree_status") or attestation.get("receipt_status")
    if not ree_hash and not ree_status:
        return ""
    return (
        f"<span>{escape(str(ree_status or 'present'))}</span> "
        f"<code>{escape(_short(str(ree_hash or '')))}</code>"
    )


def _render_tx_cell(receipt: dict[str, object]) -> str:
    tx_hash = receipt.get("tx_hash")
    explorer_url = receipt.get("explorer_url")
    if not tx_hash:
        return ""
    if explorer_url:
        return (
            f'<a href="{escape(str(explorer_url))}">'
            f'<code class="hash-chip" title="{escape(str(tx_hash))}">'
            f"{escape(_short(str(tx_hash)))}</code></a>"
        )
    return (
        f'<code class="hash-chip" title="{escape(str(tx_hash))}">'
        f"{escape(_short(str(tx_hash)))}</code>"
    )


def _render_compact_id(value: object, *, length: int = 22) -> str:
    text = str(value or "")
    if not text:
        return ""
    return (
        f'<code class="id-chip compact-id" title="{escape(text)}">'
        f"{escape(_short(text, length=length))}</code>"
    )


def _render_identity_stack(peer_id: object, wallet: object) -> str:
    return (
        '<div class="identity-stack">'
        '<div class="identity-line"><span class="identity-label">peer</span>'
        f"{_render_compact_id(peer_id, length=24)}</div>"
        '<div class="identity-line"><span class="identity-label">wallet</span>'
        f"{_render_compact_id(wallet, length=24)}</div>"
        "</div>"
    )


def _render_agent_registry(
    provenance_ledger: list[dict[str, object]],
    run_metadata: dict[str, object],
) -> str:
    if not provenance_ledger:
        rows = '<tr><td colspan="5">No agent registry evidence recorded.</td></tr>'
    else:
        attestations = _by_role(run_metadata.get("verification_attestations"))
        reputation_by_role = _reputation_by_role(run_metadata.get("reputation_updates"))
        rows = "".join(
            (
                "<tr>"
                f"<td>{escape(str(record.get('node_role', '')))}</td>"
                f"<td>{escape(str(record.get('service_name', '')))}</td>"
                "<td>"
                f"{_render_identity_stack(record.get('peer_id'), attestations.get(str(record.get('node_role', '')), {}).get('agent_wallet'))}"
                "</td>"
                f'<td><span class="status status-{escape(_status_class(str(record.get("status", ""))))}">{escape(str(record.get("status", "")))}</span></td>'
                f"<td>{escape(reputation_by_role.get(str(record.get('node_role', '')), ''))}</td>"
                "</tr>"
            )
            for record in provenance_ledger
        )
    return (
        '<section class="agent-registry">'
        "<h3>Agent Registry</h3>"
        '<table class="ledger-table compact-table agent-registry-table">'
        "<thead><tr><th>Role</th><th>Service</th><th>Identity</th>"
        "<th>Status</th><th>Rep.</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
        "</section>"
    )


def _render_proof_details(run_metadata: dict[str, object]) -> str:
    attestations = run_metadata.get("verification_attestations")
    receipts = run_metadata.get("chain_receipts")
    lines: list[str] = []
    if isinstance(attestations, list):
        for item in attestations:
            if not isinstance(item, dict):
                continue
            role = str(item.get("node_role", ""))
            details = [
                ("output_hash", item.get("output_hash")),
                ("attestation_hash", item.get("attestation_hash")),
                ("verifier_signature", item.get("verifier_signature")),
                ("ree_receipt_hash", item.get("ree_receipt_hash")),
                ("ree_prompt_hash", item.get("ree_prompt_hash")),
                ("ree_tokens_hash", item.get("ree_tokens_hash")),
                ("ree_model_name", item.get("ree_model_name")),
                ("receipt_status", item.get("receipt_status")),
            ]
            lines.extend(
                _render_proof_detail_line(role, key, value)
                for key, value in details
                if value
            )
    if isinstance(receipts, list):
        for receipt in receipts:
            if not isinstance(receipt, dict):
                continue
            role = str(receipt.get("role") or receipt.get("kind") or "")
            details = [
                ("tx_hash", receipt.get("tx_hash")),
                ("explorer_url", receipt.get("explorer_url")),
                ("ree_receipt_hash", receipt.get("ree_receipt_hash")),
                ("native_test_payout_wei", receipt.get("native_test_payout_wei")),
            ]
            lines.extend(
                _render_proof_detail_line(role, key, value)
                for key, value in details
                if value
            )
    if not lines:
        lines.append("<li>No full proof metadata recorded for this run.</li>")
    return (
        '<section class="proof-details" id="proof-details">'
        "<h3>Proof Details</h3>"
        "<ul>" + "".join(lines) + "</ul>"
        "</section>"
    )


def _render_proof_detail_line(role: str, key: str, value: object) -> str:
    return (
        "<li>"
        f"<span>{escape(role or 'run')} / {escape(key)}</span>"
        f'<code class="hash-chip">{escape(str(value))}</code>'
        "</li>"
    )


def _render_reputation_panel(
    run_metadata: dict[str, object],
    indexed_projection: ChainEventsProjection,
) -> str:
    updates = run_metadata.get("reputation_updates")
    rows: list[str] = []
    if isinstance(updates, list):
        for update in updates:
            if not isinstance(update, dict):
                continue
            rows.append(
                "<tr>"
                f"<td>{escape(str(update.get('node_role', '')))}</td>"
                f"<td>{_render_compact_id(update.get('peer_id'), length=26)}</td>"
                f"<td>{escape(str(update.get('verifier_status', '')))}</td>"
                f"<td>{escape(str(update.get('reputation_points', '')))}</td>"
                "</tr>"
            )
    for entry in indexed_projection.agent_leaderboard:
        rows.append(
            "<tr>"
            f"<td>{escape(entry.node_role)}</td>"
            f"<td>{_render_compact_id(entry.agent_wallet, length=26)}</td>"
            "<td>indexed_chain</td>"
            f"<td>{entry.reputation_points:.2f}</td>"
            "</tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="4">No reputation evidence recorded.</td></tr>')
    return (
        '<section class="reputation-panel">'
        "<h3>Reputation Ledger</h3>"
        '<table class="ledger-table compact-table reputation-table">'
        "<thead><tr><th>Role</th><th>Peer / Wallet</th><th>Status</th>"
        "<th>Points</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</section>"
    )


def _render_indexed_events_panel(indexed_projection: ChainEventsProjection) -> str:
    return (
        '<section class="indexed-events-panel">'
        "<h3>Indexed Events</h3>"
        '<dl class="metric-grid">'
        f"<div><dt>Tasks</dt><dd>{len(indexed_projection.tasks)}</dd></div>"
        f"<div><dt>Contributions</dt><dd>{len(indexed_projection.contributions)}</dd></div>"
        f"<div><dt>Verifications</dt><dd>{len(indexed_projection.verifications)}</dd></div>"
        f"<div><dt>Reputation</dt><dd>{len(indexed_projection.reputations)}</dd></div>"
        "</dl>"
        "</section>"
    )


def _has_ree_evidence(run_metadata: dict[str, object]) -> bool:
    attestations = run_metadata.get("verification_attestations")
    if isinstance(attestations, list):
        for item in attestations:
            if isinstance(item, dict) and (
                item.get("ree_receipt_hash") or item.get("receipt_status")
            ):
                return True
    receipts = run_metadata.get("chain_receipts")
    if isinstance(receipts, list):
        return any(
            isinstance(item, dict)
            and (item.get("ree_receipt_hash") or item.get("ree_status"))
            for item in receipts
        )
    return False


def _status_for_mode(mode: str) -> str:
    if mode in {"live-axl", "mesh-axl", "axl-mcp"}:
        return "confirmed"
    if mode == "offline-demo-preview":
        return "warning"
    if mode == "no-run":
        return "missing"
    return "warning"


def _status_for_receipts(run_metadata: dict[str, object]) -> str:
    status = str(run_metadata.get("receipt_status") or "")
    if status:
        return _status_class(status)
    return "missing"


def _status_class(status: str) -> str:
    normalized = status.strip().lower().replace(" ", "-").replace("_", "-")
    if not normalized:
        return "missing"
    if normalized in {"not-configured", "not-present"}:
        return normalized
    return normalized


def _roles_status(provenance_ledger: list[dict[str, object]]) -> str:
    if not provenance_ledger:
        return "missing"
    statuses = {str(record.get("status", "")) for record in provenance_ledger}
    if statuses <= {"completed"}:
        return "completed"
    if any(
        status in {"failed", "error", "invalid_response", "timed_out", "missing"}
        for status in statuses
    ):
        return "partial"
    return "recorded"


def _verification_status(run_metadata: dict[str, object]) -> str:
    attestations = run_metadata.get("verification_attestations")
    if not isinstance(attestations, list) or not attestations:
        return "not present"
    statuses = [
        str(item.get("status"))
        for item in attestations
        if isinstance(item, dict) and item.get("status")
    ]
    if statuses and all(status == "accepted" for status in statuses):
        return "accepted"
    if any(status == "rejected" for status in statuses):
        return "rejected"
    return statuses[0] if statuses else "recorded"


def _reputation_by_role(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for update in value:
        if not isinstance(update, dict) or not update.get("node_role"):
            continue
        result[str(update["node_role"])] = (
            f"{float(update.get('reputation_points', 0.0)):.2f}"
        )
    return result


def _render_run_metadata(run_metadata: dict[str, object]) -> str:
    if not run_metadata:
        return (
            '<section class="run-metadata">'
            "<h3>Run Metadata</h3>"
            "<p>No run metadata recorded.</p>"
            "</section>"
        )

    keys = (
        "run_mode",
        "transport",
        "axl_local_base_url",
        "axl_topology_path",
        "axl_mcp_router_url",
        "receipt_status",
    )
    rows = "".join(
        (
            "<tr>"
            f"<th>{escape(key)}</th>"
            f"<td><code>{escape(str(run_metadata.get(key, '')))}</code></td>"
            "</tr>"
        )
        for key in keys
        if run_metadata.get(key)
    )
    dispatch_targets = run_metadata.get("dispatch_targets", [])
    if isinstance(dispatch_targets, list) and dispatch_targets:
        rows += (
            "<tr><th>dispatch_targets</th>"
            f"<td><code>{escape(', '.join(str(item) for item in dispatch_targets))}</code></td></tr>"
        )
    rows += _render_graph_state(run_metadata.get("graph_state"))
    rows += _render_reputation_updates(run_metadata.get("reputation_updates"))
    rows += _render_chain_receipts(run_metadata.get("chain_receipts", []))
    return (
        '<section class="run-metadata">'
        "<h3>Run Metadata</h3>"
        '<table class="ledger-table">'
        f"<tbody>{rows}</tbody>"
        "</table>"
        "</section>"
    )


def _render_graph_state(graph_state: object) -> str:
    if not isinstance(graph_state, dict):
        return ""
    nodes = graph_state.get("nodes", [])
    if not isinstance(nodes, list) or not nodes:
        return ""

    parts: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        label = " / ".join(
            str(value)
            for value in (
                node.get("id"),
                node.get("type"),
                node.get("status"),
            )
            if value
        )
        if node.get("optional"):
            label = f"{label} / optional"
        if label:
            parts.append(label)
    if not parts:
        return ""
    return (
        f"<tr><th>graph_state</th><td><code>{escape(', '.join(parts))}</code></td></tr>"
    )


def _render_reputation_updates(reputation_updates: object) -> str:
    if not isinstance(reputation_updates, list) or not reputation_updates:
        return ""

    parts: list[str] = []
    for update in reputation_updates:
        if not isinstance(update, dict):
            continue
        label = " / ".join(
            str(value)
            for value in (
                update.get("node_role"),
                update.get("peer_id"),
                update.get("verifier_status"),
                f"{float(update.get('reputation_points', 0.0)):.2f} reputation",
            )
            if value
        )
        if label:
            parts.append(label)
    if not parts:
        return ""
    return (
        "<tr><th>reputation_updates</th>"
        f"<td><code>{escape(', '.join(parts))}</code></td></tr>"
    )


def _render_chain_receipts(chain_receipts: object) -> str:
    if not isinstance(chain_receipts, list) or not chain_receipts:
        return ""

    lines: list[str] = []
    for receipt in chain_receipts:
        if not isinstance(receipt, dict):
            continue
        label = " / ".join(
            str(value)
            for value in (
                receipt.get("kind"),
                receipt.get("role"),
                receipt.get("status"),
            )
            if value
        )
        tx_hash = receipt.get("tx_hash")
        explorer_url = receipt.get("explorer_url")
        error = receipt.get("error")
        ree_receipt_hash = receipt.get("ree_receipt_hash")
        ree_status = receipt.get("ree_status")
        native_test_payout_wei = receipt.get("native_test_payout_wei")
        if explorer_url and tx_hash:
            ree_suffix = ""
            if ree_receipt_hash:
                ree_label = escape(str(ree_status or "ree"))
                ree_hash = escape(str(ree_receipt_hash)[:18] + "...")
                ree_suffix = f' &middot; REE <span class="ree-status">{ree_label}</span> <code title="{escape(str(ree_receipt_hash))}">{ree_hash}</code>'
            payout_suffix = ""
            if native_test_payout_wei:
                payout_suffix = (
                    " &middot; native test payout "
                    f"<code>{escape(str(native_test_payout_wei))} wei</code>"
                )
            lines.append(
                f'{escape(label)}: <a href="{escape(str(explorer_url))}">'
                f"<code>{escape(str(tx_hash))}</code></a>{ree_suffix}{payout_suffix}"
            )
        elif error:
            lines.append(f"{escape(label)}: {escape(str(error))}")

    if not lines:
        return ""
    return f"<tr><th>chain_receipts</th><td>{'<br>'.join(lines)}</td></tr>"


def _render_node_rows(provenance_ledger: list[dict[str, object]]) -> str:
    if not provenance_ledger:
        return (
            '<tr><td colspan="4">No node participation recorded for this job.</td></tr>'
        )

    rows: list[str] = []
    for record in provenance_ledger:
        rows.append(
            (
                "<tr>"
                f"<td>{escape(str(record.get('node_role', '')))}</td>"
                f"<td>{escape(str(record.get('peer_id', '')))}</td>"
                f"<td>{escape(str(record.get('service_name', '')))}</td>"
                f"<td>{escape(str(record.get('transport', '')))}</td>"
                f"<td>{escape(str(record.get('status', '')))}</td>"
                f"<td>{escape(str(record.get('latency_ms', '')))}</td>"
                f"<td>{escape(str(record.get('selection_reason', '')))}</td>"
                f"<td>{escape(_format_attempted_peers(record))}</td>"
                f"<td><code>{escape(str(record.get('dispatch_target', '')))}</code></td>"
                "</tr>"
            )
        )
    return "".join(rows)


def _format_attempted_peers(record: dict[str, object]) -> str:
    attempted_peer_ids = record.get("attempted_peer_ids")
    if not isinstance(attempted_peer_ids, list):
        return ""
    return " -> ".join(str(peer_id) for peer_id in attempted_peer_ids)


def _render_topology(topology_snapshot: dict[str, object] | None) -> str:
    if topology_snapshot is None:
        return (
            '<section class="topology-panel"><h3>Topology Snapshot</h3>'
            "<p>No topology snapshot recorded.</p></section>"
        )

    peers_value = topology_snapshot.get("peers", [])
    peers = peers_value if isinstance(peers_value, list) else []
    peer_items = "".join(
        f"<li>{escape(str(peer))}</li>" for peer in peers if isinstance(peer, str)
    )

    local_peer = escape(
        str(
            topology_snapshot.get("local_peer_id")
            or topology_snapshot.get("our_public_key")
            or ""
        )
    )
    mode = escape(str(topology_snapshot.get("mode", "live-axl")))
    tree_value = topology_snapshot.get("tree", [])
    tree = tree_value if isinstance(tree_value, list) else []
    tree_items = "".join(
        f"<li><code>{escape(str(node.get('public_key', '')))}</code></li>"
        for node in tree
        if isinstance(node, dict)
    )
    return (
        '<section class="topology-panel">'
        "<h3>Topology Snapshot</h3>"
        f"<p>Mode: <code>{mode}</code></p>"
        f"<p>Local peer: <code>{local_peer}</code></p>"
        f"<ul>{peer_items}</ul>"
        f"<ul>{tree_items}</ul>"
        "</section>"
    )


def _short(value: str, length: int = 18) -> str:
    if not value:
        return ""
    if len(value) <= length:
        return value
    return f"{value[:length]}..."


async def _parse_urlencoded_body(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[0] if values else "" for key, values in parsed.items()}


def _build_thesis_request(form: dict[str, str]) -> ThesisRequest:
    try:
        return ThesisRequest.model_validate(
            {
                "thesis": form.get("thesis", ""),
                "asset": form.get("asset", ""),
                "horizon_days": form.get("horizon_days", ""),
            }
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(),
        ) from exc


def _fixture_to_request(fixture: DemoFixture) -> ThesisRequest:
    return ThesisRequest(
        thesis=fixture.thesis,
        asset=fixture.asset,
        horizon_days=fixture.horizon_days,
    )
