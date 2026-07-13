import asyncio
from pathlib import Path

from app.axl.registry import AXLRegistry
from app.config.settings import Settings
from app.identity.hashing import canonical_json_hash
from app.nodes.chain_analyst.metrics import compute_metrics
from app.nodes.chain_analyst.rpc import FixtureRPC
from app.nodes.chain_analyst.service import ChainAnalystService
from app.nodes.server import analyze_payload
from app.schemas.contracts import TaskSpec


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "nodes"
    / "chain_analyst"
    / "fixtures"
    / "chain_state.json"
)


def test_chain_analyst_response_is_deterministic() -> None:
    task = _task()
    service = ChainAnalystService(rpc=FixtureRPC(FIXTURE))

    first = service.analyze(task=task)
    second = service.analyze(task=task)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert canonical_json_hash(first) == canonical_json_hash(second)
    assert first.node_role == "chain_analyst"
    assert first.receipt_status is None
    assert first.ree_receipt_hash is None
    assert any(item.startswith("metrics_hash:") for item in first.citations)


def test_pinned_block_changes_metrics() -> None:
    rpc = FixtureRPC(FIXTURE)

    latest = compute_metrics(rpc.fetch_chain_state())
    earlier = compute_metrics(rpc.fetch_chain_state(block_number=17832380))

    assert latest.block_number == 17832500
    assert earlier.block_number == 17832380
    assert latest.contribution_count > earlier.contribution_count


def test_node_server_handles_chain_analyst_role() -> None:
    settings = Settings()
    response = asyncio.run(
        analyze_payload(
            payload={
                "role": "chain_analyst",
                "job_id": "job-chain-node",
                "thesis": "ETH can rally on stronger settlement demand.",
                "asset": "ETH",
                "horizon_days": 30,
                "block_number": 17832380,
            },
            settings=settings,
            registry=AXLRegistry(settings),
            llm_client=object(),
        )
    )

    assert response.node_role == "chain_analyst"
    assert response.peer_id == settings.chain_analyst_peer_id
    assert "block:17832380" in response.citations


def _task() -> TaskSpec:
    return TaskSpec(
        job_id="job-chain-analyst-test",
        thesis="ETH can rally on stronger settlement demand.",
        asset="ETH",
        horizon_days=30,
    )
