import asyncio
import json
from pathlib import Path

import httpx
from httpx import ASGITransport

from app.coordinator.service import CoordinatorDispatchResult
from app.coordinator.synthesis import MemoSynthesisService
from app.demo.fixtures import get_demo_fixture
from app.identity.hashing import canonical_json_hash
from app.main import app
from app.schemas.contracts import (
    FinalMemo,
    ProvenanceRecord,
    ScenarioView,
    ThesisRequest,
)
from app.store import JobStore


REE_FIXTURES = Path(__file__).parent / "fixtures" / "ree"


class FailingLLMClient:
    async def complete(self, model: str, messages: list[dict[str, str]]) -> str:
        raise RuntimeError("force fallback path")


class StubCoordinator:
    async def dispatch(
        self,
        job_id: str,
        request: ThesisRequest,
    ) -> CoordinatorDispatchResult:
        return CoordinatorDispatchResult(
            responses=[],
            topology_snapshot={
                "local_peer_id": "peer-coordinator-test",
                "peers": [],
            },
            market_snapshot={},
            news_headlines=[],
        )


def test_home_page_renders_form_and_latest_job_summary(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert '<form action="/demo/submit" method="post">' in html
    assert '<form action="/demo/replay/eth-etf-flow" method="post">' in html
    assert "Latest Job" in html
    assert "Run Evidence" in html
    assert "Run Metadata" in html
    assert "Job ID:" in html
    assert "Will ETH validate this thesis over 30 days" in html
    assert "peer-regime-test" in html
    assert "Topology Snapshot" in html


def test_hero_precedes_completed_run_when_available(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_trace_ledger(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert html.index("Proof Console") < html.index("Latest Verified Run")
    assert html.index("Run Another Thesis") < html.index("Latest Verified Run")
    assert html.index("Verify Run") > html.index("Latest Verified Run")
    assert 'class="tab-pane active" id="tab-ledger"' in html
    assert 'id="tab-timeline"' in html
    assert "Create Verifiable Run" in html
    assert "Dispatch Agent Swarm" not in html
    assert "Do not trust the memo. Verify every specialist behind it." in html


def test_demo_submit_redirects_back_to_home_with_new_job(tmp_path: Path) -> None:
    asyncio.run(_configure_empty_store(tmp_path))

    async def _exercise() -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            submit_response = await client.post(
                "/demo/submit",
                data={
                    "thesis": "ETH can rally on improving ETF flows.",
                    "asset": "ETH",
                    "horizon_days": "30",
                },
            )
            home_response = await client.get("/")
            return submit_response, home_response

    submit_response, home_response = asyncio.run(_exercise())

    assert submit_response.status_code == 303
    assert submit_response.headers["location"] == "/"
    assert "Latest Job" in home_response.text
    assert "ETH can rally on improving ETF flows." in home_response.text


def test_demo_submit_returns_422_for_invalid_horizon(tmp_path: Path) -> None:
    asyncio.run(_configure_empty_store(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            return await client.post(
                "/demo/submit",
                data={
                    "thesis": "ETH can rally on improving ETF flows.",
                    "asset": "ETH",
                    "horizon_days": "abc",
                },
            )

    response = asyncio.run(_exercise())

    assert response.status_code == 422
    assert "horizon_days" in response.text


def test_demo_replay_fixture_redirects_back_to_home_with_fixture_job(
    tmp_path: Path,
) -> None:
    asyncio.run(_configure_empty_store(tmp_path))

    async def _exercise() -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            follow_redirects=False,
        ) as client:
            replay_response = await client.post("/demo/replay/eth-etf-flow")
            home_response = await client.get("/")
            return replay_response, home_response

    replay_response, home_response = asyncio.run(_exercise())

    assert replay_response.status_code == 303
    assert replay_response.headers["location"] == "/"
    assert "ETH ETF Flow Case" in home_response.text
    assert (
        "ETH can rally on improving ETF flows and stable liquidity."
        in home_response.text
    )


def test_demo_fixture_loader_returns_replayable_thesis_case() -> None:
    fixture = get_demo_fixture("eth-etf-flow")

    assert fixture.fixture_id == "eth-etf-flow"
    assert fixture.asset == "ETH"
    assert fixture.horizon_days == 30
    assert "ETF flows" in fixture.thesis
    assert fixture.to_dict()["title"] == "ETH ETF Flow Case"


def test_home_page_handles_live_axl_topology_shape(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_axl_topology(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    assert "Topology Snapshot" in response.text
    assert "axl-public-key-test" in response.text


def test_home_page_renders_chain_receipt_status(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_chain_receipts(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    assert "receipt_status" in response.text
    assert "confirmed" in response.text
    assert "https://gensyn-testnet.explorer.alchemy.com/tx/0xabc123" in response.text


def test_home_page_renders_graph_state(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_graph_state(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    assert "graph_state" in response.text
    assert "regime / specialist / completed" in response.text
    assert "risk / specialist / missing / optional" in response.text


def test_home_page_renders_reputation_updates(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_reputation_updates(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    assert "reputation_updates" in response.text
    assert "regime / peer-regime-test / accepted / 84.00 reputation" in response.text


def test_home_page_renders_native_test_payout_receipt(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_native_test_payout(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    assert "native test payout" in response.text
    assert "1000000000 wei" in response.text


def test_trace_ledger_renders_receipts(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_trace_ledger(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert "Task Trace" in html
    assert "peer-risk-test" in html
    assert "0x00000000000000000000000000000000000000a1" in html
    assert "0xabcdeabcdeabcd" in html
    assert "validated" in html
    assert "https://gensyn-testnet.explorer.alchemy.com/tx/0xtrace123" in html


def test_home_page_renders_proof_console_layout(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_trace_ledger(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert "Do not trust the memo. Verify every specialist behind it." in html
    assert "Proof capabilities" in html
    assert "Run Timeline" in html
    assert "Agent Registry" in html
    assert "Task Trace" in html
    assert "Proof Details" in html
    assert "Reputation Ledger" in html
    assert "Indexed Events" in html
    assert "job-memo" in html


def test_proof_details_render_full_receipt_metadata(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_trace_ledger(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert "risk / output_hash" in html
    assert "0xabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcde" in html
    assert "risk / attestation_hash" in html
    assert "0xattestationhash000000000000000000000000000000000000000000000000" in html
    assert "risk / verifier_signature" in html
    assert "0xverifiersignature0000000000000000000000000000000000000000000000" in html
    assert "risk / ree_receipt_hash" in html
    assert (
        "sha256:36ae72fccc5e179a6986d0af614546170ed60be0d0ab953e05978a10c7a9dcb3"
        in html
    )
    assert "contribution / explorer_url" not in html
    assert "https://gensyn-testnet.explorer.alchemy.com/tx/0xtrace123" in html


def test_proof_console_renders_verify_action(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_trace_ledger(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    latest_job = asyncio.run(app.state.job_store.get_latest_job())
    assert latest_job is not None
    html = response.text
    assert "Verify Run" in html
    assert f"/jobs/{latest_job.job_id}/verify" in html
    assert "open proof bundle" in html


def test_proof_console_renders_precise_verification_states(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_trace_ledger(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert "<td>output_hashes</td>" in html
    assert "<td>attestations</td>" in html
    assert "<td>ree</td>" in html
    assert "<td>chain</td>" in html
    assert "validated" in html
    assert "present" in html


def test_proof_console_renders_phase_17_verification_labels(
    tmp_path: Path,
) -> None:
    asyncio.run(_configure_completed_job_with_phase_17_evidence(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert "verified from stored specialist payload" in html
    assert "validated from receipt body" in html
    assert "verified by RPC" in html
    assert "present only" in html


def test_proof_console_renders_failed_incomplete_payload_binding(
    tmp_path: Path,
) -> None:
    asyncio.run(_configure_completed_job_with_phase_17_evidence(tmp_path))
    latest_job = asyncio.run(app.state.job_store.get_latest_job())
    assert latest_job is not None
    run_metadata = dict(latest_job.run_metadata)
    run_metadata["specialist_responses"] = [
        response
        for response in run_metadata.get("specialist_responses", [])
        if isinstance(response, dict) and response.get("node_role") == "risk"
    ]
    run_metadata["chain_receipts"] = [
        {
            "kind": "contribution",
            "role": "risk",
            "status": "confirmed",
            "tx_hash": "0xphase17",
            "rpc_status": "confirmed",
        },
        {
            "kind": "contribution",
            "role": "narrative",
            "status": "confirmed",
            "tx_hash": "0xpresentonly",
        },
    ]
    asyncio.run(
        app.state.job_store.complete_job(
            job_id=latest_job.job_id,
            memo=FinalMemo.model_validate(latest_job.memo),
            provenance_ledger=latest_job.provenance_ledger,
            run_metadata=run_metadata,
            topology_snapshot=latest_job.topology_snapshot,
        )
    )

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert "stored specialist payload verification failed" in html
    assert "checked by RPC" in html


def test_risk_ree_hero_proof_renders_receipt_components(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_trace_ledger(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert "Risk REE Proof" in html
    assert "Qwen/Qwen3-0.6B" in html
    assert "sha256:prompt000000000000000000000000000000000000000000000000000000" in html
    assert "sha256:tokens000000000000000000000000000000000000000000000000000000" in html
    assert (
        "sha256:36ae72fccc5e179a6986d0af614546170ed60be0d0ab953e05978a10c7a9dcb3"
        in html
    )
    assert "0xabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcde" in html
    assert "0xtrace123" in html


def test_proof_console_wraps_long_identifiers(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_long_identifiers(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert "overflow-wrap: anywhere" in html
    assert "hash-chip" in html
    assert "id-chip" in html
    assert "peer-" + "a" * 96 in html
    assert "0x" + "b" * 64 in html


async def _configure_completed_job(tmp_path: Path) -> None:
    app.state.job_store = JobStore(database_url=f"sqlite:///{tmp_path / 'jobs.db'}")
    app.state.memo_synthesis_service = MemoSynthesisService(
        llm_client=FailingLLMClient()
    )
    await app.state.job_store.initialize()
    job = await app.state.job_store.create_job(
        ThesisRequest(
            thesis="ETH can rally on improving ETF flows.",
            asset="ETH",
            horizon_days=30,
        )
    )
    await app.state.job_store.complete_job(
        job_id=job.job_id,
        memo=FinalMemo(
            job_id=job.job_id,
            normalized_thesis=(
                "Will ETH validate this thesis over 30 days: "
                "ETH can rally on improving ETF flows."
            ),
            scenarios=ScenarioView(bull=0.42, base=0.36, bear=0.22),
            catalysts=["ETF flows remain constructive."],
            risks=["Macro volatility can pressure beta assets."],
            invalidation_triggers=["ETH loses the recent support range."],
            provenance=[
                ProvenanceRecord(
                    node_role="regime",
                    peer_id="peer-regime-test",
                    timestamp="2026-04-24T00:00:00Z",
                )
            ],
            partial=False,
            partial_reason=None,
        ),
        provenance_ledger=[
            {
                "node_role": "regime",
                "peer_id": "peer-regime-test",
                "service_name": "regime_analyst",
                "transport": "axl-mcp",
                "dispatch_target": "/mcp/peer-regime-test/regime_analyst",
                "status": "completed",
                "latency_ms": 12.5,
            }
        ],
        run_metadata={
            "run_mode": "live-axl",
            "transport": "axl-mcp",
            "axl_local_base_url": "http://127.0.0.1:9002",
            "dispatch_targets": ["/mcp/peer-regime-test/regime_analyst"],
        },
        topology_snapshot={
            "local_peer_id": "peer-coordinator-test",
            "peers": ["peer-regime-test"],
        },
    )


async def _configure_completed_job_with_graph_state(tmp_path: Path) -> None:
    await _configure_completed_job(tmp_path)
    latest_job = await app.state.job_store.get_latest_job()
    assert latest_job is not None
    run_metadata = dict(latest_job.run_metadata)
    run_metadata["graph_state"] = {
        "nodes": [
            {
                "id": "regime",
                "type": "specialist",
                "status": "completed",
                "optional": False,
            },
            {
                "id": "risk",
                "type": "specialist",
                "status": "missing",
                "optional": True,
            },
        ],
        "edges": [["regime", "verifier"], ["risk", "verifier"]],
    }
    await app.state.job_store.complete_job(
        job_id=latest_job.job_id,
        memo=FinalMemo.model_validate(latest_job.memo),
        provenance_ledger=latest_job.provenance_ledger,
        run_metadata=run_metadata,
        topology_snapshot=latest_job.topology_snapshot,
    )


async def _configure_completed_job_with_reputation_updates(tmp_path: Path) -> None:
    await _configure_completed_job(tmp_path)
    latest_job = await app.state.job_store.get_latest_job()
    assert latest_job is not None
    run_metadata = dict(latest_job.run_metadata)
    run_metadata["reputation_updates"] = [
        {
            "job_id": latest_job.job_id,
            "node_role": "regime",
            "peer_id": "peer-regime-test",
            "verifier_status": "accepted",
            "verifier_score": 0.84,
            "credit_eligible": True,
            "reputation_points": 84.0,
            "reason": "verifier_score_credit",
        }
    ]
    await app.state.job_store.complete_job(
        job_id=latest_job.job_id,
        memo=FinalMemo.model_validate(latest_job.memo),
        provenance_ledger=latest_job.provenance_ledger,
        run_metadata=run_metadata,
        topology_snapshot=latest_job.topology_snapshot,
    )


async def _configure_completed_job_with_native_test_payout(tmp_path: Path) -> None:
    await _configure_completed_job(tmp_path)
    latest_job = await app.state.job_store.get_latest_job()
    assert latest_job is not None
    run_metadata = dict(latest_job.run_metadata)
    run_metadata.update(
        {
            "receipt_status": "confirmed",
            "chain_receipts": [
                {
                    "kind": "reputation",
                    "role": "risk",
                    "status": "confirmed",
                    "tx_hash": "0xpayout123",
                    "explorer_url": (
                        "https://gensyn-testnet.explorer.alchemy.com/tx/0xpayout123"
                    ),
                    "native_test_payout_wei": 1_000_000_000,
                }
            ],
        }
    )
    await app.state.job_store.complete_job(
        job_id=latest_job.job_id,
        memo=FinalMemo.model_validate(latest_job.memo),
        provenance_ledger=latest_job.provenance_ledger,
        run_metadata=run_metadata,
        topology_snapshot=latest_job.topology_snapshot,
    )


async def _configure_completed_job_with_trace_ledger(tmp_path: Path) -> None:
    await _configure_completed_job(tmp_path)
    latest_job = await app.state.job_store.get_latest_job()
    assert latest_job is not None
    run_metadata = dict(latest_job.run_metadata)
    run_metadata.update(
        {
            "receipt_status": "confirmed",
            "verification_attestations": [
                {
                    "job_id": latest_job.job_id,
                    "node_role": "risk",
                    "peer_id": "peer-risk-test",
                    "status": "accepted",
                    "score": 0.91,
                    "reasons": ["receipt_status=validated"],
                    "agent_wallet": "0x00000000000000000000000000000000000000a1",
                    "output_hash": (
                        "0xabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcdeabcde"
                    ),
                    "attestation_hash": (
                        "0xattestationhash000000000000000000000000000000000000000000000000"
                    ),
                    "verifier_signature": (
                        "0xverifiersignature0000000000000000000000000000000000000000000000"
                    ),
                    "ree_receipt_hash": (
                        "sha256:36ae72fccc5e179a6986d0af614546170ed60be0d0ab953e05978a10c7a9dcb3"
                    ),
                    "receipt_status": "validated",
                    "ree_prompt_hash": (
                        "sha256:prompt000000000000000000000000000000000000000000000000000000"
                    ),
                    "ree_tokens_hash": (
                        "sha256:tokens000000000000000000000000000000000000000000000000000000"
                    ),
                    "ree_model_name": "Qwen/Qwen3-0.6B",
                }
            ],
            "chain_receipts": [
                {
                    "kind": "contribution",
                    "role": "risk",
                    "status": "confirmed",
                    "tx_hash": "0xtrace123",
                    "explorer_url": (
                        "https://gensyn-testnet.explorer.alchemy.com/tx/0xtrace123"
                    ),
                    "ree_receipt_hash": (
                        "sha256:36ae72fccc5e179a6986d0af614546170ed60be0d0ab953e05978a10c7a9dcb3"
                    ),
                    "ree_status": "validated",
                }
            ],
        }
    )
    await app.state.job_store.complete_job(
        job_id=latest_job.job_id,
        memo=FinalMemo.model_validate(latest_job.memo),
        provenance_ledger=[
            {
                "node_role": "risk",
                "peer_id": "peer-risk-test",
                "service_name": "risk_analyst",
                "transport": "axl-mcp",
                "dispatch_target": "/mcp/peer-risk-test/risk_analyst",
                "status": "completed",
                "latency_ms": 22.5,
            }
        ],
        run_metadata=run_metadata,
        topology_snapshot=latest_job.topology_snapshot,
    )


async def _configure_completed_job_with_phase_17_evidence(tmp_path: Path) -> None:
    await _configure_completed_job(tmp_path)
    latest_job = await app.state.job_store.get_latest_job()
    assert latest_job is not None
    receipt_body = json.loads((REE_FIXTURES / "valid_receipt.json").read_text())
    receipt_hash = str(receipt_body["receipt_hash"])
    response_payload = {
        "job_id": latest_job.job_id,
        "node_role": "risk",
        "peer_id": "peer-risk-test",
        "summary": "Risk output is structured.",
        "scenario_view": {"bull": 0.3, "base": 0.4, "bear": 0.3},
        "signals": [],
        "risks": ["Support can fail."],
        "confidence": 0.72,
        "citations": [],
        "timestamp": "2026-05-02T00:00:00Z",
        "agent_wallet": "0x00000000000000000000000000000000000000a1",
        "ree_receipt_hash": receipt_hash,
        "receipt_status": "validated",
        "ree_prompt_hash": receipt_body["prompt_hash"],
        "ree_tokens_hash": receipt_body["tokens_hash"],
        "ree_model_name": receipt_body["model_name"],
        "ree_receipt_body": receipt_body,
        "ree_receipt_path": None,
    }
    output_hash = canonical_json_hash(response_payload)
    narrative_payload = {
        "job_id": latest_job.job_id,
        "node_role": "narrative",
        "peer_id": "peer-narrative-test",
        "summary": "Narrative support is constructive.",
        "scenario_view": {"bull": 0.4, "base": 0.4, "bear": 0.2},
        "signals": ["ETF flows remain constructive."],
        "risks": [],
        "confidence": 0.7,
        "citations": [],
        "timestamp": "2026-05-02T00:00:00Z",
        "agent_wallet": None,
        "ree_receipt_hash": None,
        "receipt_status": None,
        "ree_prompt_hash": None,
        "ree_tokens_hash": None,
        "ree_model_name": None,
        "ree_receipt_body": None,
        "ree_receipt_path": None,
    }
    narrative_output_hash = canonical_json_hash(narrative_payload)
    run_metadata = dict(latest_job.run_metadata)
    run_metadata.update(
        {
            "verification_attestations": [
                {
                    "job_id": latest_job.job_id,
                    "node_role": "risk",
                    "peer_id": "peer-risk-test",
                    "status": "accepted",
                    "score": 0.91,
                    "agent_wallet": "0x00000000000000000000000000000000000000a1",
                    "output_hash": output_hash,
                    "ree_receipt_hash": receipt_hash,
                    "receipt_status": "validated",
                    "ree_receipt_body": receipt_body,
                },
                {
                    "job_id": latest_job.job_id,
                    "node_role": "narrative",
                    "peer_id": "peer-narrative-test",
                    "status": "accepted",
                    "score": 0.7,
                    "output_hash": narrative_output_hash,
                },
            ],
            "specialist_responses": [response_payload, narrative_payload],
            "chain_receipts": [
                {
                    "kind": "contribution",
                    "role": "risk",
                    "status": "confirmed",
                    "tx_hash": "0xphase17",
                    "rpc_status": "confirmed",
                    "explorer_url": (
                        "https://gensyn-testnet.explorer.alchemy.com/tx/0xphase17"
                    ),
                }
            ],
        }
    )
    await app.state.job_store.complete_job(
        job_id=latest_job.job_id,
        memo=FinalMemo.model_validate(latest_job.memo),
        provenance_ledger=[
            {
                "node_role": "risk",
                "peer_id": "peer-risk-test",
                "service_name": "risk_analyst",
                "transport": "axl-mcp",
                "dispatch_target": "/mcp/peer-risk-test/risk_analyst",
                "status": "completed",
                "latency_ms": 22.5,
            }
        ],
        run_metadata=run_metadata,
        topology_snapshot=latest_job.topology_snapshot,
    )


async def _configure_completed_job_with_long_identifiers(tmp_path: Path) -> None:
    await _configure_completed_job_with_trace_ledger(tmp_path)
    latest_job = await app.state.job_store.get_latest_job()
    assert latest_job is not None
    long_peer = "peer-" + "a" * 96
    run_metadata = dict(latest_job.run_metadata)
    run_metadata["verification_attestations"] = [
        {
            "job_id": latest_job.job_id,
            "node_role": "risk",
            "peer_id": long_peer,
            "status": "accepted",
            "score": 0.91,
            "agent_wallet": "0x00000000000000000000000000000000000000a1",
            "output_hash": "0x" + "b" * 64,
            "attestation_hash": "0x" + "c" * 64,
            "verifier_signature": "0x" + "d" * 128,
            "ree_receipt_hash": "sha256:" + "e" * 64,
            "receipt_status": "validated",
        }
    ]
    await app.state.job_store.complete_job(
        job_id=latest_job.job_id,
        memo=FinalMemo.model_validate(latest_job.memo),
        provenance_ledger=[
            {
                "node_role": "risk",
                "peer_id": long_peer,
                "service_name": "risk_analyst",
                "transport": "axl-mcp",
                "dispatch_target": f"/mcp/{long_peer}/risk_analyst",
                "status": "completed",
                "latency_ms": 22.5,
            }
        ],
        run_metadata=run_metadata,
        topology_snapshot={
            "local_peer_id": "peer-coordinator-test",
            "peers": [long_peer],
        },
    )


async def _configure_empty_store(tmp_path: Path) -> None:
    app.state.job_store = JobStore(database_url=f"sqlite:///{tmp_path / 'jobs.db'}")
    app.state.coordinator_service = StubCoordinator()
    app.state.memo_synthesis_service = MemoSynthesisService(
        llm_client=FailingLLMClient()
    )
    await app.state.job_store.initialize()


async def _configure_completed_job_with_axl_topology(tmp_path: Path) -> None:
    await _configure_completed_job(tmp_path)
    latest_job = await app.state.job_store.get_latest_job()
    assert latest_job is not None
    await app.state.job_store.complete_job(
        job_id=latest_job.job_id,
        memo=FinalMemo.model_validate(latest_job.memo),
        provenance_ledger=latest_job.provenance_ledger,
        run_metadata=latest_job.run_metadata,
        topology_snapshot={
            "our_public_key": "axl-public-key-test",
            "peers": None,
            "tree": [
                {
                    "public_key": "axl-public-key-test",
                    "parent": "axl-public-key-test",
                    "sequence": 1,
                }
            ],
        },
    )


async def _configure_completed_job_with_chain_receipts(tmp_path: Path) -> None:
    await _configure_completed_job(tmp_path)
    latest_job = await app.state.job_store.get_latest_job()
    assert latest_job is not None
    run_metadata = dict(latest_job.run_metadata)
    run_metadata.update(
        {
            "receipt_status": "confirmed",
            "chain_receipts": [
                {
                    "kind": "task",
                    "status": "confirmed",
                    "tx_hash": "0xabc123",
                    "explorer_url": (
                        "https://gensyn-testnet.explorer.alchemy.com/tx/0xabc123"
                    ),
                }
            ],
        }
    )
    await app.state.job_store.complete_job(
        job_id=latest_job.job_id,
        memo=FinalMemo.model_validate(latest_job.memo),
        provenance_ledger=latest_job.provenance_ledger,
        run_metadata=run_metadata,
        topology_snapshot=latest_job.topology_snapshot,
    )


def test_home_page_renders_ree_receipt_status_on_contribution(tmp_path: Path) -> None:
    asyncio.run(_configure_completed_job_with_ree_receipts(tmp_path))

    async def _exercise() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.get("/")

    response = asyncio.run(_exercise())

    assert response.status_code == 200
    html = response.text
    assert "receipt_status" in html
    assert "confirmed" in html
    assert "https://gensyn-testnet.explorer.alchemy.com/tx/0xcontrib456" in html
    assert "ree-status" in html
    assert "validated" in html
    assert "0xc90e11f80d66bd" in html


async def _configure_completed_job_with_ree_receipts(tmp_path: Path) -> None:
    await _configure_completed_job(tmp_path)
    latest_job = await app.state.job_store.get_latest_job()
    assert latest_job is not None
    run_metadata = dict(latest_job.run_metadata)
    run_metadata.update(
        {
            "receipt_status": "confirmed",
            "chain_receipts": [
                {
                    "kind": "contribution",
                    "role": "risk",
                    "status": "confirmed",
                    "tx_hash": "0xcontrib456",
                    "explorer_url": (
                        "https://gensyn-testnet.explorer.alchemy.com/tx/0xcontrib456"
                    ),
                    "ree_receipt_hash": (
                        "0xc90e11f80d66bd541821f6c465c14f99fad76c041731dd5922309880d374f498"
                    ),
                    "ree_status": "validated",
                }
            ],
        }
    )
    await app.state.job_store.complete_job(
        job_id=latest_job.job_id,
        memo=FinalMemo.model_validate(latest_job.memo),
        provenance_ledger=latest_job.provenance_ledger,
        run_metadata=run_metadata,
        topology_snapshot=latest_job.topology_snapshot,
    )
