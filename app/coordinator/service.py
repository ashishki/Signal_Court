"""Coordinator dispatch workflow for specialist fan-out."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Protocol

from app.axl.registry import AXLCapabilityRegistry, AXLRegistry
from app.evaluation.reputation import build_reputation_updates
from app.integrations.market_data import MarketDataProvider
from app.integrations.news_feed import NewsFeedProvider
from app.observability.provenance import NodeExecutionRecord
from app.orchestration.executor import ExecutionPlan, GraphExecutor
from app.orchestration.graph import DEFAULT_WORKFLOW_GRAPH, WorkflowGraph
from app.orchestration.state import build_graph_state
from app.schemas.contracts import (
    SpecialistResponse,
    TaskSpec,
    ThesisRequest,
    VerificationAttestation,
)


class AXLTransport(Protocol):
    async def fetch_topology(self) -> dict[str, Any]: ...

    async def dispatch_specialist(
        self,
        peer_id: str,
        service_name: str,
        payload: dict[str, Any],
    ) -> SpecialistResponse: ...


class ResponseVerifier(Protocol):
    def verify_responses(
        self,
        *,
        task: TaskSpec,
        responses: list[SpecialistResponse],
    ) -> list[VerificationAttestation]: ...


class InvalidSpecialistResponseError(ValueError):
    """Raised when a transport response does not match its dispatch context."""


@dataclass(frozen=True)
class CoordinatorDispatchResult:
    responses: list[SpecialistResponse]
    topology_snapshot: dict[str, Any]
    market_snapshot: dict[str, Any]
    news_headlines: list[str]
    input_sources: list[dict[str, Any]] = field(default_factory=list)
    rejected_responses: list[SpecialistResponse] = field(default_factory=list)
    verification_attestations: list[VerificationAttestation] = field(
        default_factory=list
    )
    run_metadata: dict[str, Any] = field(default_factory=dict)
    node_execution_records: list[NodeExecutionRecord] = field(default_factory=list)
    partial: bool = False
    missing_roles: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RoleDispatchOutcome:
    response: SpecialistResponse | None
    execution_record: NodeExecutionRecord


class CoordinatorService:
    def __init__(
        self,
        axl_client: AXLTransport,
        registry: AXLRegistry,
        market_data_provider: MarketDataProvider,
        news_feed_provider: NewsFeedProvider,
        llm_client: Any,
        verifier: ResponseVerifier | None = None,
        workflow_graph: WorkflowGraph = DEFAULT_WORKFLOW_GRAPH,
    ) -> None:
        self._axl_client = axl_client
        self._registry = registry
        self._capability_registry = AXLCapabilityRegistry(registry)
        self._market_data_provider = market_data_provider
        self._news_feed_provider = news_feed_provider
        self._llm_client = llm_client
        self._verifier = verifier
        self._workflow_graph = workflow_graph
        self._graph_executor = GraphExecutor(workflow_graph)
        self._execution_plan = self._graph_executor.build_plan()

    async def dispatch(
        self,
        job_id: str,
        request: ThesisRequest,
    ) -> CoordinatorDispatchResult:
        topology_snapshot = await self._axl_client.fetch_topology()
        run_mode = str(topology_snapshot.get("mode", "live-axl"))
        market_snapshot = await self._market_data_provider.fetch_snapshot(request)
        news_headlines = await self._news_feed_provider.fetch_headlines(request)
        input_sources = await self._build_input_sources(
            request=request,
            market_snapshot=market_snapshot,
            news_headlines=news_headlines,
        )

        roles = self._execution_plan.specialist_roles
        results = await asyncio.gather(
            *[
                self._dispatch_role(
                    role=role,
                    job_id=job_id,
                    request=request,
                    market_snapshot=market_snapshot,
                    news_headlines=news_headlines,
                    run_mode=run_mode,
                    topology_snapshot=topology_snapshot,
                )
                for role in roles
            ]
        )

        responses: list[SpecialistResponse] = []
        missing_roles: list[str] = []
        node_execution_records: list[NodeExecutionRecord] = []
        for role, result in zip(roles, results, strict=True):
            node_execution_records.append(result.execution_record)
            if result.response is None:
                missing_roles.append(role)
                continue
            responses.append(result.response)

        rejected_responses: list[SpecialistResponse] = []
        verification_attestations: list[VerificationAttestation] = []
        if self._verifier is not None:
            responses, rejected_responses, verification_attestations = (
                self._verify_responses(
                    job_id=job_id,
                    request=request,
                    responses=responses,
                )
            )

        return CoordinatorDispatchResult(
            responses=responses,
            rejected_responses=rejected_responses,
            verification_attestations=verification_attestations,
            topology_snapshot=topology_snapshot,
            market_snapshot=market_snapshot,
            news_headlines=news_headlines,
            input_sources=input_sources,
            run_metadata=self._build_run_metadata(
                run_mode=run_mode,
                records=node_execution_records,
                missing_roles=missing_roles,
                verification_attestations=verification_attestations,
                specialist_responses=[*responses, *rejected_responses],
                execution_plan=self._execution_plan,
                input_sources=input_sources,
                verifier_ran=(
                    self._verifier is not None
                    and self._execution_plan.verifier_node_id is not None
                ),
                synthesis_ran=self._execution_plan.synthesis_node_id is not None,
            ),
            node_execution_records=node_execution_records,
            partial=bool(missing_roles or rejected_responses),
            missing_roles=missing_roles,
        )

    def _verify_responses(
        self,
        *,
        job_id: str,
        request: ThesisRequest,
        responses: list[SpecialistResponse],
    ) -> tuple[
        list[SpecialistResponse],
        list[SpecialistResponse],
        list[VerificationAttestation],
    ]:
        if self._verifier is None:
            return responses, [], []

        task = TaskSpec(
            job_id=job_id,
            thesis=request.thesis,
            asset=request.asset,
            horizon_days=request.horizon_days,
        )
        attestations = self._verifier.verify_responses(
            task=task,
            responses=responses,
        )
        attestation_by_role = {
            attestation.node_role: attestation for attestation in attestations
        }
        accepted: list[SpecialistResponse] = []
        rejected: list[SpecialistResponse] = []
        for response in responses:
            attestation = attestation_by_role.get(response.node_role)
            if attestation is not None and attestation.status == "accepted":
                accepted.append(response)
            else:
                rejected.append(response)
        return accepted, rejected, attestations

    async def _build_input_sources(
        self,
        *,
        request: ThesisRequest,
        market_snapshot: dict[str, Any],
        news_headlines: list[str],
    ) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        market_source = market_snapshot.get("source_metadata")
        if isinstance(market_source, dict):
            sources.append(
                {
                    "input_role": "regime",
                    "input_name": "market_snapshot",
                    **market_source,
                }
            )

        source_metadata = getattr(
            self._news_feed_provider, "fetch_source_metadata", None
        )
        if callable(source_metadata):
            news_sources = await source_metadata(request, news_headlines)
            for headline, source in zip(news_headlines, news_sources, strict=False):
                if isinstance(source, dict):
                    sources.append(
                        {
                            "input_role": "narrative",
                            "input_name": "news_headline",
                            "text": headline,
                            **source,
                        }
                    )

        return sources

    async def _dispatch_role(
        self,
        role: str,
        job_id: str,
        request: ThesisRequest,
        market_snapshot: dict[str, Any],
        news_headlines: list[str],
        run_mode: str,
        topology_snapshot: dict[str, Any],
    ) -> RoleDispatchOutcome:
        transport = (
            "offline-preview" if run_mode == "offline-demo-preview" else "axl-mcp"
        )
        payload = self._build_payload(
            role=role,
            job_id=job_id,
            request=request,
            market_snapshot=market_snapshot,
            news_headlines=news_headlines,
        )
        started_at = perf_counter()
        candidate_count = len(
            self._capability_registry.list_candidates(
                role,
                topology_snapshot=topology_snapshot,
            )
        )
        failed_peer_ids: set[str] = set()
        attempted_peer_ids: list[str] = []
        last_selection = None
        last_status = "error"

        while len(failed_peer_ids) < candidate_count:
            selection = self._capability_registry.select_for_role(
                role,
                topology_snapshot=topology_snapshot,
                failed_peer_ids=failed_peer_ids,
            )
            last_selection = selection
            peer_service = selection.service
            dispatch_target = f"/mcp/{peer_service.peer_id}/{peer_service.service_name}"
            attempted_peer_ids.append(peer_service.peer_id)

            try:
                response = await self._axl_client.dispatch_specialist(
                    peer_id=peer_service.peer_id,
                    service_name=peer_service.service_name,
                    payload=payload,
                )
                _validate_response_context(
                    response=response,
                    job_id=job_id,
                    role=role,
                    peer_id=peer_service.peer_id,
                )
            except TimeoutError:
                last_status = "timed_out"
                failed_peer_ids.add(peer_service.peer_id)
                continue
            except InvalidSpecialistResponseError:
                last_status = "invalid_response"
                failed_peer_ids.add(peer_service.peer_id)
                continue
            except Exception:
                last_status = "error"
                failed_peer_ids.add(peer_service.peer_id)
                continue

            return RoleDispatchOutcome(
                response=response,
                execution_record=NodeExecutionRecord(
                    node_role=role,
                    peer_id=peer_service.peer_id,
                    status="completed",
                    latency_ms=_elapsed_ms(started_at),
                    service_name=peer_service.service_name,
                    transport=transport,
                    dispatch_target=dispatch_target,
                    selection_reason=_fallback_reason(
                        selection.reason,
                        attempted_peer_ids=attempted_peer_ids,
                    ),
                    attempted_peer_ids=_audit_attempts(attempted_peer_ids),
                ),
            )

        if last_selection is None:
            raise ValueError(f"AXLRegistry: no peer candidates for role '{role}'")

        peer_service = last_selection.service
        return RoleDispatchOutcome(
            response=None,
            execution_record=NodeExecutionRecord(
                node_role=role,
                peer_id=peer_service.peer_id,
                status=last_status,
                latency_ms=_elapsed_ms(started_at),
                service_name=peer_service.service_name,
                transport=transport,
                dispatch_target=f"/mcp/{peer_service.peer_id}/{peer_service.service_name}",
                selection_reason=_fallback_reason(
                    last_selection.reason,
                    attempted_peer_ids=attempted_peer_ids,
                    exhausted=True,
                ),
                attempted_peer_ids=_audit_attempts(attempted_peer_ids),
            ),
        )

    def _build_payload(
        self,
        role: str,
        job_id: str,
        request: ThesisRequest,
        market_snapshot: dict[str, Any],
        news_headlines: list[str],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "role": role,
            "asset": request.asset,
            "horizon_days": request.horizon_days,
            "thesis": request.thesis,
        }

        if role == "regime":
            payload["snapshot"] = market_snapshot
        elif role == "narrative":
            payload["headlines"] = news_headlines

        return payload

    def _build_run_metadata(
        self,
        run_mode: str,
        records: list[NodeExecutionRecord],
        missing_roles: list[str],
        verification_attestations: list[VerificationAttestation],
        specialist_responses: list[SpecialistResponse],
        execution_plan: ExecutionPlan,
        input_sources: list[dict[str, Any]],
        verifier_ran: bool,
        synthesis_ran: bool,
    ) -> dict[str, Any]:
        completed_roles = [
            record.node_role for record in records if record.status == "completed"
        ]
        rejected_roles = [
            attestation.node_role
            for attestation in verification_attestations
            if attestation.status == "rejected"
        ]
        graph_state = build_graph_state(
            graph=self._workflow_graph,
            completed_roles=completed_roles,
            missing_roles=missing_roles,
            rejected_roles=rejected_roles,
            verifier_ran=verifier_ran,
            synthesis_ran=synthesis_ran,
        )
        metadata: dict[str, Any] = {
            "run_mode": run_mode,
            "expected_roles": [record.node_role for record in records],
            "completed_roles": completed_roles,
            "missing_roles": missing_roles,
            "rejected_roles": rejected_roles,
            "verification_attestations": [
                attestation.model_dump() for attestation in verification_attestations
            ],
            "specialist_responses": [
                response.model_dump(mode="json") for response in specialist_responses
            ],
            "reputation_updates": [
                update.to_dict()
                for update in build_reputation_updates(verification_attestations)
            ],
            "execution_plan": execution_plan.to_dict(),
            "workflow_graph": self._workflow_graph.to_dict(),
            "graph_state": graph_state.to_dict(),
            "dispatch_targets": [
                record.dispatch_target for record in records if record.dispatch_target
            ],
            "peer_selection": [
                _peer_selection_metadata(record)
                for record in records
                if record.selection_reason
            ],
        }
        if input_sources:
            metadata["input_sources"] = input_sources
        transport_metadata = getattr(self._axl_client, "run_metadata", None)
        if callable(transport_metadata):
            metadata.update(transport_metadata())
        verifier_metadata = getattr(self._verifier, "run_metadata", None)
        if callable(verifier_metadata):
            metadata.update(verifier_metadata())
        return metadata


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)


def _validate_response_context(
    *,
    response: SpecialistResponse,
    job_id: str,
    role: str,
    peer_id: str,
) -> None:
    mismatches = [
        field
        for field, expected, observed in (
            ("job_id", job_id, response.job_id),
            ("node_role", role, response.node_role),
            ("peer_id", peer_id, response.peer_id),
        )
        if observed != expected
    ]
    if mismatches:
        raise InvalidSpecialistResponseError(
            "specialist response context mismatch: " + ",".join(mismatches)
        )


def _fallback_reason(
    reason: str,
    *,
    attempted_peer_ids: list[str],
    exhausted: bool = False,
) -> str:
    failed_before_success = attempted_peer_ids[:-1]
    suffixes: list[str] = []
    if failed_before_success:
        suffixes.append(f"fallback_from={','.join(failed_before_success)}")
    if exhausted and len(attempted_peer_ids) > 1:
        suffixes.append(f"attempts_exhausted={','.join(attempted_peer_ids)}")
    if not suffixes:
        return reason
    return f"{reason}; {'; '.join(suffixes)}"


def _audit_attempts(attempted_peer_ids: list[str]) -> list[str]:
    return list(attempted_peer_ids) if len(attempted_peer_ids) > 1 else []


def _peer_selection_metadata(record: NodeExecutionRecord) -> dict[str, object]:
    metadata: dict[str, object] = {
        "node_role": record.node_role,
        "peer_id": record.peer_id,
        "selection_reason": record.selection_reason,
    }
    if record.attempted_peer_ids:
        metadata["attempted_peer_ids"] = list(record.attempted_peer_ids)
    return metadata
