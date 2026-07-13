import asyncio
import time

import pytest

from app.axl.registry import AXLRegistry
from app.config.settings import Settings
from app.coordinator.service import CoordinatorService
from app.schemas.contracts import (
    ScenarioView,
    SpecialistResponse,
    TaskSpec,
    ThesisRequest,
    VerificationAttestation,
)


class StubAXLClient:
    def __init__(self) -> None:
        self.topology_snapshot = {
            "local_peer_id": "peer-coordinator-example",
            "peers": [
                "peer-regime-example",
                "peer-narrative-example",
                "peer-risk-example",
            ],
        }
        self.call_log: list[tuple[str, str]] = []
        self.dispatch_roles: list[str] = []
        self.payloads: list[dict[str, object]] = []

    async def fetch_topology(self) -> dict[str, object]:
        self.call_log.append(("topology", "fetch"))
        return self.topology_snapshot

    async def dispatch_specialist(
        self,
        peer_id: str,
        service_name: str,
        payload: dict[str, object],
    ) -> SpecialistResponse:
        self.call_log.append(("dispatch", str(payload["role"])))
        self.dispatch_roles.append(str(payload["role"]))
        self.payloads.append(payload)
        await asyncio.sleep(0.05)
        return SpecialistResponse(
            job_id=str(payload["job_id"]),
            node_role=str(payload["role"]),
            peer_id=peer_id,
            summary=f"{payload['role']} summary",
            scenario_view=ScenarioView(bull=0.3, base=0.4, bear=0.3),
            signals=[service_name],
            risks=[],
            confidence=0.6,
            citations=[],
            timestamp="2026-04-22T00:00:00Z",
        )


class FallbackAXLClient(StubAXLClient):
    def __init__(self) -> None:
        super().__init__()
        self.topology_snapshot = {
            "local_peer_id": "peer-coordinator-example",
            "peers": [
                "peer-regime-example",
                "peer-narrative-example",
                "peer-risk-a",
                "peer-risk-b",
            ],
        }
        self.attempted_peer_ids: list[str] = []

    async def dispatch_specialist(
        self,
        peer_id: str,
        service_name: str,
        payload: dict[str, object],
    ) -> SpecialistResponse:
        self.attempted_peer_ids.append(peer_id)
        if peer_id == "peer-risk-a":
            raise TimeoutError("first risk peer timed out")
        return await super().dispatch_specialist(peer_id, service_name, payload)


class ContextSubstitutionAXLClient(StubAXLClient):
    def __init__(self, *, field: str, replacement: str) -> None:
        super().__init__()
        self.field = field
        self.replacement = replacement

    async def dispatch_specialist(
        self,
        peer_id: str,
        service_name: str,
        payload: dict[str, object],
    ) -> SpecialistResponse:
        response = await super().dispatch_specialist(peer_id, service_name, payload)
        if payload["role"] != "risk":
            return response
        return response.model_copy(update={self.field: self.replacement})


class StubMarketDataProvider:
    def __init__(self) -> None:
        self.requests: list[ThesisRequest] = []

    async def fetch_snapshot(self, request: ThesisRequest) -> dict[str, float]:
        self.requests.append(request)
        return {"price_return": 0.08, "volatility": 0.18}


class StubNewsFeedProvider:
    def __init__(self) -> None:
        self.requests: list[ThesisRequest] = []

    async def fetch_headlines(self, request: ThesisRequest) -> list[str]:
        self.requests.append(request)
        return [
            "ETF flow expectations improve",
            "Macro data keeps liquidity hopes alive",
        ]


class StubVerifier:
    def __init__(self, *, reject_role: str | None = None) -> None:
        self.reject_role = reject_role
        self.calls: list[tuple[TaskSpec, list[str]]] = []

    def verify_responses(
        self,
        *,
        task: TaskSpec,
        responses: list[SpecialistResponse],
    ) -> list[VerificationAttestation]:
        self.calls.append((task, [response.node_role for response in responses]))
        return [
            VerificationAttestation(
                job_id=response.job_id,
                node_role=response.node_role,
                peer_id=response.peer_id,
                status=(
                    "rejected" if response.node_role == self.reject_role else "accepted"
                ),
                score=0.0 if response.node_role == self.reject_role else 0.8,
                reasons=["stub_verifier"],
            )
            for response in responses
        ]


def test_coordinator_dispatches_and_collects_all_specialist_responses() -> None:
    axl_client = StubAXLClient()
    market_data_provider = StubMarketDataProvider()
    news_feed_provider = StubNewsFeedProvider()
    service = CoordinatorService(
        axl_client=axl_client,
        registry=AXLRegistry(Settings()),
        market_data_provider=market_data_provider,
        news_feed_provider=news_feed_provider,
        llm_client=object(),
    )
    request = ThesisRequest(
        thesis="ETH can extend higher on ETF demand.",
        asset="ETH",
        horizon_days=30,
    )

    started_at = time.perf_counter()
    result = asyncio.run(
        service.dispatch(job_id="job-coordinator-123", request=request)
    )
    elapsed = time.perf_counter() - started_at

    assert len(result.responses) == 3
    assert {response.node_role for response in result.responses} == {
        "regime",
        "narrative",
        "risk",
    }
    assert result.partial is False
    assert result.topology_snapshot == axl_client.topology_snapshot
    assert market_data_provider.requests == [request]
    assert news_feed_provider.requests == [request]
    assert axl_client.dispatch_roles == ["regime", "narrative", "risk"]
    assert [
        response["node_role"]
        for response in result.run_metadata["specialist_responses"]
    ] == [
        "regime",
        "narrative",
        "risk",
    ]
    assert elapsed < 0.12


def test_verifier_runs_before_synthesis() -> None:
    axl_client = StubAXLClient()
    verifier = StubVerifier()
    service = CoordinatorService(
        axl_client=axl_client,
        registry=AXLRegistry(Settings()),
        market_data_provider=StubMarketDataProvider(),
        news_feed_provider=StubNewsFeedProvider(),
        llm_client=object(),
        verifier=verifier,
    )
    request = ThesisRequest(
        thesis="ETH can extend higher on ETF demand.",
        asset="ETH",
        horizon_days=30,
    )

    result = asyncio.run(service.dispatch(job_id="job-verifier-order", request=request))

    assert verifier.calls == [
        (
            TaskSpec(
                job_id="job-verifier-order",
                thesis="ETH can extend higher on ETF demand.",
                asset="ETH",
                horizon_days=30,
            ),
            ["regime", "narrative", "risk"],
        )
    ]
    assert axl_client.dispatch_roles == ["regime", "narrative", "risk"]
    assert len(result.responses) == 3
    assert result.rejected_responses == []
    assert [att.status for att in result.verification_attestations] == [
        "accepted",
        "accepted",
        "accepted",
    ]


def test_coordinator_filters_rejected_specialist_responses() -> None:
    verifier = StubVerifier(reject_role="risk")
    service = CoordinatorService(
        axl_client=StubAXLClient(),
        registry=AXLRegistry(Settings()),
        market_data_provider=StubMarketDataProvider(),
        news_feed_provider=StubNewsFeedProvider(),
        llm_client=object(),
        verifier=verifier,
    )
    request = ThesisRequest(
        thesis="ETH can extend higher on ETF demand.",
        asset="ETH",
        horizon_days=30,
    )

    result = asyncio.run(
        service.dispatch(job_id="job-verifier-reject", request=request)
    )

    assert [response.node_role for response in result.responses] == [
        "regime",
        "narrative",
    ]
    assert [response.node_role for response in result.rejected_responses] == ["risk"]
    assert result.partial is True
    assert result.run_metadata["rejected_roles"] == ["risk"]


def test_peer_selection_reason_is_recorded() -> None:
    service = CoordinatorService(
        axl_client=StubAXLClient(),
        registry=AXLRegistry(Settings()),
        market_data_provider=StubMarketDataProvider(),
        news_feed_provider=StubNewsFeedProvider(),
        llm_client=object(),
    )
    request = ThesisRequest(
        thesis="ETH can extend higher on ETF demand.",
        asset="ETH",
        horizon_days=30,
    )

    result = asyncio.run(service.dispatch(job_id="job-peer-selection", request=request))

    assert result.run_metadata["peer_selection"] == [
        {
            "node_role": "regime",
            "peer_id": "peer-regime-example",
            "selection_reason": "capability:topology-up",
        },
        {
            "node_role": "narrative",
            "peer_id": "peer-narrative-example",
            "selection_reason": "capability:topology-up",
        },
        {
            "node_role": "risk",
            "peer_id": "peer-risk-example",
            "selection_reason": "capability:topology-up",
        },
    ]


def test_coordinator_falls_back_to_next_peer_candidate() -> None:
    axl_client = FallbackAXLClient()
    service = CoordinatorService(
        axl_client=axl_client,
        registry=AXLRegistry(
            Settings(
                risk_peer_candidates="peer-risk-a:risk_analyst,peer-risk-b:risk_analyst"
            )
        ),
        market_data_provider=StubMarketDataProvider(),
        news_feed_provider=StubNewsFeedProvider(),
        llm_client=object(),
    )
    request = ThesisRequest(
        thesis="ETH can extend higher on ETF demand.",
        asset="ETH",
        horizon_days=30,
    )

    result = asyncio.run(service.dispatch(job_id="job-peer-fallback", request=request))

    risk_response = next(
        response for response in result.responses if response.node_role == "risk"
    )
    risk_record = next(
        record for record in result.node_execution_records if record.node_role == "risk"
    )
    assert risk_response.peer_id == "peer-risk-b"
    assert risk_record.peer_id == "peer-risk-b"
    assert risk_record.status == "completed"
    assert risk_record.attempted_peer_ids == ["peer-risk-a", "peer-risk-b"]
    assert risk_record.selection_reason == (
        "capability:topology-up; fallback_from=peer-risk-a"
    )
    assert result.run_metadata["peer_selection"][-1] == {
        "node_role": "risk",
        "peer_id": "peer-risk-b",
        "selection_reason": "capability:topology-up; fallback_from=peer-risk-a",
        "attempted_peer_ids": ["peer-risk-a", "peer-risk-b"],
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("job_id", "attacker-job"),
        ("node_role", "attacker-role"),
        ("peer_id", "attacker-peer"),
    ),
)
def test_coordinator_rejects_response_context_substitution_before_verification(
    field: str,
    replacement: str,
) -> None:
    verifier = StubVerifier()
    service = CoordinatorService(
        axl_client=ContextSubstitutionAXLClient(
            field=field,
            replacement=replacement,
        ),
        registry=AXLRegistry(Settings()),
        market_data_provider=StubMarketDataProvider(),
        news_feed_provider=StubNewsFeedProvider(),
        llm_client=object(),
        verifier=verifier,
    )
    request = ThesisRequest(
        thesis="ETH can extend higher on ETF demand.",
        asset="ETH",
        horizon_days=30,
    )

    result = asyncio.run(service.dispatch(job_id="job-context-bound", request=request))

    assert [response.node_role for response in result.responses] == [
        "regime",
        "narrative",
    ]
    assert result.rejected_responses == []
    assert result.missing_roles == ["risk"]
    assert result.partial is True
    assert verifier.calls[0][1] == ["regime", "narrative"]
    risk_record = next(
        record for record in result.node_execution_records if record.node_role == "risk"
    )
    assert risk_record.status == "invalid_response"
    assert risk_record.peer_id == "peer-risk-example"
    assert all(
        response["job_id"] == "job-context-bound"
        and response["node_role"] in {"regime", "narrative"}
        and response["peer_id"] != "attacker-peer"
        for response in result.run_metadata["specialist_responses"]
    )
    assert all(
        update["credit_eligible"] is False and update["reputation_points"] == 0
        for update in result.run_metadata["reputation_updates"]
    )


def test_coordinator_dispatch_payloads_are_transport_safe() -> None:
    axl_client = StubAXLClient()
    service = CoordinatorService(
        axl_client=axl_client,
        registry=AXLRegistry(Settings()),
        market_data_provider=StubMarketDataProvider(),
        news_feed_provider=StubNewsFeedProvider(),
        llm_client=object(),
    )
    request = ThesisRequest(
        thesis="ETH can extend higher on ETF demand.",
        asset="ETH",
        horizon_days=30,
    )

    asyncio.run(service.dispatch(job_id="job-transport-safe", request=request))

    assert all("llm_client" not in payload for payload in axl_client.payloads)
    assert axl_client.payloads == [
        {
            "job_id": "job-transport-safe",
            "role": "regime",
            "asset": "ETH",
            "horizon_days": 30,
            "thesis": "ETH can extend higher on ETF demand.",
            "snapshot": {"price_return": 0.08, "volatility": 0.18},
        },
        {
            "job_id": "job-transport-safe",
            "role": "narrative",
            "asset": "ETH",
            "horizon_days": 30,
            "thesis": "ETH can extend higher on ETF demand.",
            "headlines": [
                "ETF flow expectations improve",
                "Macro data keeps liquidity hopes alive",
            ],
        },
        {
            "job_id": "job-transport-safe",
            "role": "risk",
            "asset": "ETH",
            "horizon_days": 30,
            "thesis": "ETH can extend higher on ETF demand.",
        },
    ]


def test_coordinator_records_topology_snapshot_per_job() -> None:
    axl_client = StubAXLClient()
    service = CoordinatorService(
        axl_client=axl_client,
        registry=AXLRegistry(Settings()),
        market_data_provider=StubMarketDataProvider(),
        news_feed_provider=StubNewsFeedProvider(),
        llm_client=object(),
    )
    request = ThesisRequest(
        thesis="ETH momentum remains constructive.",
        asset="ETH",
        horizon_days=14,
    )

    result = asyncio.run(
        service.dispatch(job_id="job-coordinator-456", request=request)
    )

    assert result.topology_snapshot == {
        "local_peer_id": "peer-coordinator-example",
        "peers": [
            "peer-regime-example",
            "peer-narrative-example",
            "peer-risk-example",
        ],
    }
    assert axl_client.call_log[0] == ("topology", "fetch")
    assert axl_client.call_log[1:] == [
        ("dispatch", "regime"),
        ("dispatch", "narrative"),
        ("dispatch", "risk"),
    ]


def test_coordinator_records_axl_dispatch_evidence_per_role() -> None:
    service = CoordinatorService(
        axl_client=StubAXLClient(),
        registry=AXLRegistry(Settings()),
        market_data_provider=StubMarketDataProvider(),
        news_feed_provider=StubNewsFeedProvider(),
        llm_client=object(),
    )
    request = ThesisRequest(
        thesis="ETH momentum remains constructive.",
        asset="ETH",
        horizon_days=14,
    )

    result = asyncio.run(
        service.dispatch(job_id="job-coordinator-789", request=request)
    )

    assert [record.to_dict() for record in result.node_execution_records] == [
        {
            "node_role": "regime",
            "peer_id": "peer-regime-example",
            "status": "completed",
            "latency_ms": result.node_execution_records[0].latency_ms,
            "service_name": "regime_analyst",
            "transport": "axl-mcp",
            "dispatch_target": "/mcp/peer-regime-example/regime_analyst",
            "selection_reason": "capability:topology-up",
        },
        {
            "node_role": "narrative",
            "peer_id": "peer-narrative-example",
            "status": "completed",
            "latency_ms": result.node_execution_records[1].latency_ms,
            "service_name": "narrative_analyst",
            "transport": "axl-mcp",
            "dispatch_target": "/mcp/peer-narrative-example/narrative_analyst",
            "selection_reason": "capability:topology-up",
        },
        {
            "node_role": "risk",
            "peer_id": "peer-risk-example",
            "status": "completed",
            "latency_ms": result.node_execution_records[2].latency_ms,
            "service_name": "risk_analyst",
            "transport": "axl-mcp",
            "dispatch_target": "/mcp/peer-risk-example/risk_analyst",
            "selection_reason": "capability:topology-up",
        },
    ]
