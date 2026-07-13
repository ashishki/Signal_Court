"""Role to peer/service mapping for AXL specialist nodes."""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings


@dataclass(frozen=True)
class PeerService:
    peer_id: str
    service_name: str


@dataclass(frozen=True)
class PeerCapability:
    role: str
    peer_id: str
    service_name: str
    wallet: str = ""
    health: str = "unknown"
    reputation_score: float = 0.0
    latency_ms: float | None = None


@dataclass(frozen=True)
class PeerSelection:
    service: PeerService
    reason: str
    capability: PeerCapability


class AXLRegistry:
    def __init__(self, settings: Settings) -> None:
        self._services = {
            "regime": PeerService(
                peer_id=settings.regime_peer_id,
                service_name=settings.regime_service_name,
            ),
            "narrative": PeerService(
                peer_id=settings.narrative_peer_id,
                service_name=settings.narrative_service_name,
            ),
            "risk": PeerService(
                peer_id=settings.risk_peer_id,
                service_name=settings.risk_service_name,
            ),
            "chain_analyst": PeerService(
                peer_id=settings.chain_analyst_peer_id,
                service_name=settings.chain_analyst_service_name,
            ),
        }
        self._candidates = {
            "regime": _parse_peer_candidates(
                settings.regime_peer_candidates,
                fallback=self._services["regime"],
            ),
            "narrative": _parse_peer_candidates(
                settings.narrative_peer_candidates,
                fallback=self._services["narrative"],
            ),
            "risk": _parse_peer_candidates(
                settings.risk_peer_candidates,
                fallback=self._services["risk"],
            ),
            "chain_analyst": _parse_peer_candidates(
                settings.chain_analyst_peer_candidates,
                fallback=self._services["chain_analyst"],
            ),
        }

    def get_service_for_role(self, role: str) -> PeerService:
        service = self._services.get(role)
        if service is None:
            raise ValueError(f"AXLRegistry: unknown role '{role}'")
        return service

    def get_candidates_for_role(self, role: str) -> list[PeerService]:
        candidates = self._candidates.get(role)
        if candidates is None:
            raise ValueError(f"AXLRegistry: unknown role '{role}'")
        return candidates


class AXLCapabilityRegistry:
    def __init__(self, registry: AXLRegistry) -> None:
        self._registry = registry

    def list_candidates(
        self,
        role: str,
        topology_snapshot: dict[str, object] | None = None,
        reputation_updates: list[dict[str, object]] | None = None,
        failed_peer_ids: set[str] | None = None,
    ) -> list[PeerCapability]:
        services = self._registry.get_candidates_for_role(role)
        topology_peer_ids = _topology_peer_ids(topology_snapshot)
        failed_ids = failed_peer_ids or set()
        return [
            PeerCapability(
                role=role,
                peer_id=peer_service.peer_id,
                service_name=peer_service.service_name,
                health=_candidate_health(
                    peer_id=peer_service.peer_id,
                    topology_peer_ids=topology_peer_ids,
                    failed_peer_ids=failed_ids,
                ),
                reputation_score=_peer_reputation_score(
                    role=role,
                    peer_id=peer_service.peer_id,
                    reputation_updates=reputation_updates or [],
                ),
            )
            for peer_service in services
        ]

    def select_for_role(
        self,
        role: str,
        topology_snapshot: dict[str, object] | None = None,
        reputation_updates: list[dict[str, object]] | None = None,
        failed_peer_ids: set[str] | None = None,
    ) -> PeerSelection:
        candidates = self.list_candidates(
            role,
            topology_snapshot=topology_snapshot,
            reputation_updates=reputation_updates,
            failed_peer_ids=failed_peer_ids,
        )
        selected = max(candidates, key=_candidate_rank)
        reason = _selection_reason(selected, candidate_count=len(candidates))
        return PeerSelection(
            service=PeerService(
                peer_id=selected.peer_id,
                service_name=selected.service_name,
            ),
            reason=reason,
            capability=selected,
        )


def _parse_peer_candidates(
    raw_candidates: str, fallback: PeerService
) -> list[PeerService]:
    if not raw_candidates.strip():
        return [fallback]

    candidates: list[PeerService] = []
    for raw_item in raw_candidates.split(","):
        item = raw_item.strip()
        if not item:
            continue
        if "|" in item:
            peer_id, service_name = item.split("|", 1)
        elif ":" in item:
            peer_id, service_name = item.split(":", 1)
        else:
            peer_id, service_name = item, fallback.service_name
        candidates.append(
            PeerService(
                peer_id=peer_id.strip(),
                service_name=service_name.strip() or fallback.service_name,
            )
        )
    return candidates or [fallback]


def _peer_reputation_score(
    role: str,
    peer_id: str,
    reputation_updates: list[dict[str, object]],
) -> float:
    scores = [
        float(update.get("reputation_points", 0.0))
        for update in reputation_updates
        if update.get("node_role") == role
        and str(update.get("peer_id", peer_id)) == peer_id
        and update.get("credit_eligible") is True
    ]
    return max(scores) if scores else 0.0


def _topology_peer_ids(topology_snapshot: dict[str, object] | None) -> set[str]:
    if not topology_snapshot:
        return set()

    peer_ids: set[str] = set()
    for key in ("our_public_key", "local_peer_id", "peer_id", "public_key"):
        value = topology_snapshot.get(key)
        if isinstance(value, str) and value:
            peer_ids.add(value)

    for collection_key in ("peers", "tree"):
        collection = topology_snapshot.get(collection_key)
        if not isinstance(collection, list):
            continue
        for item in collection:
            if isinstance(item, str) and item:
                peer_ids.add(item)
            elif isinstance(item, dict):
                for key in ("public_key", "peer_id", "id"):
                    value = item.get(key)
                    if isinstance(value, str) and value:
                        peer_ids.add(value)

    return peer_ids


def _candidate_health(
    *,
    peer_id: str,
    topology_peer_ids: set[str],
    failed_peer_ids: set[str],
) -> str:
    if peer_id in failed_peer_ids:
        return "failed"
    if not topology_peer_ids:
        return "configured"
    if peer_id in topology_peer_ids:
        return "up"
    return "down"


def _candidate_rank(candidate: PeerCapability) -> tuple[int, float]:
    health_rank = {
        "failed": 0,
        "down": 1,
        "configured": 2,
        "up": 3,
    }.get(candidate.health, 0)
    return health_rank, candidate.reputation_score


def _selection_reason(candidate: PeerCapability, *, candidate_count: int) -> str:
    if (
        candidate.health == "configured"
        and candidate_count == 1
        and candidate.reputation_score <= 0
    ):
        return "capability:static-role-match"

    health_reason = {
        "up": "capability:topology-up",
        "configured": "capability:configured",
        "down": "capability:topology-missing",
        "failed": "capability:previous-attempt-failed",
    }.get(candidate.health, "capability:unknown")
    if candidate.reputation_score <= 0:
        return health_reason
    return f"{health_reason},reputation-score:{candidate.reputation_score:.2f}"
