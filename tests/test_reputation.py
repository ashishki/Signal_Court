import asyncio
from pathlib import Path

from app.evaluation.reputation import ReputationUpdate, build_reputation_updates
from app.schemas.contracts import (
    FinalMemo,
    ScenarioView,
    ThesisRequest,
    VerificationAttestation,
)
from app.store import JobStore


def test_valid_contribution_increases_reputation(tmp_path: Path) -> None:
    attestation = _attestation(status="accepted", score=0.82)

    updates = build_reputation_updates([attestation])

    assert updates[0].node_role == "regime"
    assert updates[0].peer_id == "peer-regime-test"
    assert updates[0].agent_wallet == "0xFCAd0B19bB29D4674531d6f115237E16AfCE377c"
    assert updates[0].credit_eligible is True
    assert updates[0].reputation_points == 82.0
    assert updates[0].reason == "verifier_score_credit"

    leaderboard = asyncio.run(_persist_and_read_leaderboard(tmp_path, updates))

    assert [entry.to_dict() for entry in leaderboard] == [
        {
            "node_role": "regime",
            "peer_id": "peer-regime-test",
            "reputation_points": 82.0,
            "accepted_contributions": 1,
            "rejected_contributions": 0,
            "total_verifier_score": 0.82,
        }
    ]


def test_invalid_contribution_gets_no_credit(tmp_path: Path) -> None:
    attestation = _attestation(status="rejected", score=0.0)

    updates = build_reputation_updates([attestation])

    assert updates[0].reputation_points == 0.0
    assert updates[0].credit_eligible is False
    assert updates[0].reason == "no_credit_for_rejected_verifier_status"

    leaderboard = asyncio.run(_persist_and_read_leaderboard(tmp_path, updates))

    assert [entry.to_dict() for entry in leaderboard] == [
        {
            "node_role": "regime",
            "peer_id": "peer-regime-test",
            "reputation_points": 0.0,
            "accepted_contributions": 0,
            "rejected_contributions": 1,
            "total_verifier_score": 0.0,
        }
    ]


def test_unsigned_accepted_attestation_has_no_reputation_or_ranking_effect(
    tmp_path: Path,
) -> None:
    attestation = _attestation(status="accepted", score=0.99).model_copy(
        update={"signer": None, "agent_wallet": None}
    )

    updates = build_reputation_updates([attestation])

    assert updates[0].credit_eligible is False
    assert updates[0].verifier_score == 0.0
    assert updates[0].reputation_points == 0.0
    assert updates[0].reason == "no_credit_without_verified_execution_signer"
    assert asyncio.run(_persist_and_read_leaderboard(tmp_path, updates)) == []


def test_accepted_signer_wallet_mismatch_has_no_ranking_effect(tmp_path: Path) -> None:
    attestation = _attestation(status="accepted", score=0.99).model_copy(
        update={"signer": "0x00000000000000000000000000000000000000A2"}
    )

    updates = build_reputation_updates([attestation])

    assert updates[0].credit_eligible is False
    assert updates[0].verifier_score == 0.0
    assert updates[0].reputation_points == 0.0
    assert updates[0].reason == "no_credit_for_signer_wallet_mismatch"
    assert asyncio.run(_persist_and_read_leaderboard(tmp_path, updates)) == []


def _attestation(*, status: str, score: float) -> VerificationAttestation:
    return VerificationAttestation(
        job_id="job-reputation-1",
        node_role="regime",
        peer_id="peer-regime-test",
        agent_wallet="0xFCAd0B19bB29D4674531d6f115237E16AfCE377c",
        signer="0xFCAd0B19bB29D4674531d6f115237E16AfCE377c",
        output_hash="0x" + "11" * 32,
        status=status,
        score=score,
        reasons=["test"],
    )


async def _persist_and_read_leaderboard(
    tmp_path: Path,
    updates: list[ReputationUpdate],
) -> list[object]:
    store = JobStore(database_url=f"sqlite:///{tmp_path / 'jobs.db'}")
    await store.initialize()
    request = ThesisRequest(
        thesis="ETH can extend higher on ETF demand.",
        asset="ETH",
        horizon_days=30,
    )
    job = await store.create_job(request)
    await store.complete_job(
        job_id=job.job_id,
        memo=FinalMemo(
            job_id=job.job_id,
            normalized_thesis="Will ETH validate this thesis over 30 days.",
            scenarios=ScenarioView(bull=0.4, base=0.4, bear=0.2),
        ),
        run_metadata={"reputation_updates": [update.to_dict() for update in updates]},
    )
    return await store.get_reputation_leaderboard()
