"""Deterministic on-chain analyst specialist."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.identity.hashing import canonical_json_hash
from app.nodes.chain_analyst.metrics import (
    ChainMetrics,
    RoleMetric,
    compute_metrics,
    confidence_from_metrics,
)
from app.nodes.chain_analyst.rpc import RPCAdapter
from app.schemas.contracts import ScenarioView, SpecialistResponse, TaskSpec

NODE_ROLE = "chain_analyst"
SERVICE_NAME = "chain_analyst"


@dataclass
class ChainAnalystService:
    rpc: RPCAdapter
    peer_id: str = "peer-chain-analyst-001"
    agent_wallet: str | None = None

    metrics: ChainMetrics | None = field(default=None, init=False)

    def analyze(
        self,
        *,
        task: TaskSpec,
        block_number: int | None = None,
    ) -> SpecialistResponse:
        state = self.rpc.fetch_chain_state(block_number=block_number)
        metrics = compute_metrics(state)
        self.metrics = metrics
        return _build_response(
            task=task,
            metrics=metrics,
            peer_id=self.peer_id,
            agent_wallet=self.agent_wallet,
        )


def analyze(
    *,
    rpc: RPCAdapter,
    task: TaskSpec,
    peer_id: str = "peer-chain-analyst-001",
    agent_wallet: str | None = None,
    block_number: int | None = None,
) -> SpecialistResponse:
    return ChainAnalystService(
        rpc=rpc,
        peer_id=peer_id,
        agent_wallet=agent_wallet,
    ).analyze(task=task, block_number=block_number)


def _build_response(
    *,
    task: TaskSpec,
    metrics: ChainMetrics,
    peer_id: str,
    agent_wallet: str | None,
) -> SpecialistResponse:
    summary = _summary_text(metrics)
    signals = _role_signals(metrics)
    risks = _network_risks(metrics)
    scenario = _scenario_view(metrics)

    timestamp = (
        datetime.fromtimestamp(metrics.block_timestamp, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    metrics_hash = canonical_json_hash(metrics.to_dict())

    citations = [
        f"chain:{metrics.chain_id}",
        f"block:{metrics.block_number}",
        f"metrics_hash:{metrics_hash}",
    ]

    return SpecialistResponse(
        job_id=task.job_id,
        node_role=NODE_ROLE,
        peer_id=peer_id,
        summary=summary,
        scenario_view=scenario,
        signals=signals,
        risks=risks,
        confidence=confidence_from_metrics(metrics),
        citations=citations,
        timestamp=timestamp,
        agent_wallet=agent_wallet,
    )


def _summary_text(metrics: ChainMetrics) -> str:
    parts = [
        f"On-chain snapshot at block {metrics.block_number}",
        f"finalized_tasks={metrics.finalized_task_count}",
        f"contributions={metrics.contribution_count}",
        f"distinct_wallets={metrics.distinct_wallets}",
    ]
    return " | ".join(parts)


def _role_signals(metrics: ChainMetrics) -> list[str]:
    out: list[str] = []
    for role_metric in metrics.roles:
        out.append(_role_signal_line(role_metric))
    return out


def _role_signal_line(role_metric: RoleMetric) -> str:
    top = role_metric.top_peer
    if top is None:
        return f"{role_metric.role}: 0 active peers; no on-chain contributions recorded"
    return (
        f"{role_metric.role}: top peer {top.peer_id} "
        f"(reputation={top.reputation:.4f}, "
        f"contributions={top.contributions}, last_block={top.last_block}); "
        f"{role_metric.peer_count} active peers, "
        f"avg_reputation={role_metric.avg_reputation:.4f}"
    )


def _network_risks(metrics: ChainMetrics) -> list[str]:
    risks: list[str] = []
    for role_metric in metrics.roles:
        if role_metric.peer_count == 0:
            risks.append(
                f"role={role_metric.role} has no on-chain contributions; "
                f"single-source risk if dispatched"
            )
        elif role_metric.peer_count == 1:
            risks.append(
                f"role={role_metric.role} has only one active peer "
                f"({role_metric.contribution_count} contributions); no peer "
                f"diversity for fallback"
            )
        elif role_metric.avg_reputation < 0.5:
            risks.append(
                f"role={role_metric.role} avg reputation "
                f"{role_metric.avg_reputation:.4f} below 0.5; specialist "
                f"output should be discounted by verifier"
            )
    if metrics.finalized_task_count == 0:
        risks.append(
            "no finalized tasks at this block; on-chain history is empty "
            "and analyst cannot anchor reputation in completed work"
        )
    if not risks:
        risks.append("no structural on-chain risks detected at this snapshot")
    return risks


def _scenario_view(metrics: ChainMetrics) -> ScenarioView:
    coverage = _coverage_ratio(metrics)
    bull = round(0.20 + 0.50 * coverage, 4)
    bear = round(0.20 + 0.40 * (1 - coverage), 4)
    base = round(1.0 - bull - bear, 4)
    if base < 0:
        base = 0.0
        total = bull + bear
        if total > 0:
            bull = round(bull / total, 4)
            bear = round(1.0 - bull, 4)
    return ScenarioView(bull=bull, base=base, bear=bear)


def _coverage_ratio(metrics: ChainMetrics) -> float:
    if not metrics.roles:
        return 0.0
    covered = sum(1 for r in metrics.roles if r.peer_count >= 2)
    return covered / len(metrics.roles)
