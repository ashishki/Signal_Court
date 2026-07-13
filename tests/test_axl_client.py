import pytest

from app.axl.client import AXLClient
from app.axl.registry import AXLCapabilityRegistry, AXLRegistry
from app.config.settings import Settings


def test_registry_returns_peer_and_service_for_known_roles() -> None:
    settings = Settings()
    registry = AXLRegistry(settings)

    regime = registry.get_service_for_role("regime")
    narrative = registry.get_service_for_role("narrative")
    risk = registry.get_service_for_role("risk")

    assert regime.peer_id == "peer-regime-example"
    assert regime.service_name == "regime_analyst"
    assert narrative.peer_id == "peer-narrative-example"
    assert narrative.service_name == "narrative_analyst"
    assert risk.peer_id == "peer-risk-example"
    assert risk.service_name == "risk_analyst"


def test_axl_client_targets_local_bridge_mcp_path() -> None:
    settings = Settings()
    registry = AXLRegistry(settings)
    client = AXLClient(settings, registry)

    assert (
        client.build_mcp_request_path("risk")
        == "http://127.0.0.1:9002/mcp/peer-risk-example/risk_analyst"
    )
    assert client.build_mcp_request_path("regime").startswith("http://127.0.0.1:9002")


def test_axl_client_fetches_topology_from_local_bridge() -> None:
    settings = Settings()
    registry = AXLRegistry(settings)
    client = AXLClient(settings, registry)

    assert client.build_topology_path() == "http://127.0.0.1:9002/topology"


def test_registry_raises_value_error_for_unknown_role() -> None:
    settings = Settings()
    registry = AXLRegistry(settings)

    with pytest.raises(ValueError, match="unknown role 'coordinator'"):
        registry.get_service_for_role("coordinator")


def test_capability_registry_lists_role_candidates() -> None:
    settings = Settings()
    registry = AXLCapabilityRegistry(AXLRegistry(settings))

    candidates = registry.list_candidates(
        "risk",
        reputation_updates=[
            {
                "node_role": "risk",
                "peer_id": "peer-risk-example",
                "credit_eligible": True,
                "reputation_points": 91.5,
            }
        ],
    )
    selection = registry.select_for_role("risk")

    assert candidates[0].role == "risk"
    assert candidates[0].peer_id == "peer-risk-example"
    assert candidates[0].service_name == "risk_analyst"
    assert candidates[0].health == "configured"
    assert candidates[0].reputation_score == 91.5
    assert selection.service.peer_id == "peer-risk-example"
    assert selection.reason == "capability:static-role-match"


def test_capability_registry_ignores_ineligible_reputation_credit() -> None:
    registry = AXLCapabilityRegistry(AXLRegistry(Settings()))

    candidates = registry.list_candidates(
        "risk",
        reputation_updates=[
            {
                "node_role": "risk",
                "peer_id": "peer-risk-example",
                "credit_eligible": False,
                "reputation_points": 999999.0,
            }
        ],
    )

    assert candidates[0].reputation_score == 0.0


def test_capability_registry_selects_topology_live_candidate() -> None:
    settings = Settings(
        risk_peer_candidates=("peer-risk-down:risk_analyst,peer-risk-up:risk_analyst")
    )
    registry = AXLCapabilityRegistry(AXLRegistry(settings))

    candidates = registry.list_candidates(
        "risk",
        topology_snapshot={"peers": ["peer-risk-up"]},
    )
    selection = registry.select_for_role(
        "risk",
        topology_snapshot={"peers": ["peer-risk-up"]},
    )

    assert [(candidate.peer_id, candidate.health) for candidate in candidates] == [
        ("peer-risk-down", "down"),
        ("peer-risk-up", "up"),
    ]
    assert selection.service.peer_id == "peer-risk-up"
    assert selection.reason == "capability:topology-up"
