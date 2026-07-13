"""Deterministic reputation points derived from verifier attestations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from app.schemas.contracts import VerificationAttestation


@dataclass(frozen=True)
class ReputationUpdate:
    job_id: str
    node_role: str
    peer_id: str
    agent_wallet: str | None
    verifier_status: str
    verifier_score: float
    credit_eligible: bool
    reputation_points: float
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "node_role": self.node_role,
            "peer_id": self.peer_id,
            "agent_wallet": self.agent_wallet,
            "verifier_status": self.verifier_status,
            "verifier_score": self.verifier_score,
            "credit_eligible": self.credit_eligible,
            "reputation_points": self.reputation_points,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReputationLedgerEntry:
    node_role: str
    peer_id: str
    reputation_points: float
    accepted_contributions: int
    rejected_contributions: int
    total_verifier_score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "node_role": self.node_role,
            "peer_id": self.peer_id,
            "reputation_points": self.reputation_points,
            "accepted_contributions": self.accepted_contributions,
            "rejected_contributions": self.rejected_contributions,
            "total_verifier_score": self.total_verifier_score,
        }


def build_reputation_updates(
    attestations: Iterable[VerificationAttestation],
) -> list[ReputationUpdate]:
    updates: list[ReputationUpdate] = []
    for attestation in attestations:
        credit_eligible = _credit_eligible(attestation)
        updates.append(
            ReputationUpdate(
                job_id=attestation.job_id,
                node_role=attestation.node_role,
                peer_id=attestation.peer_id,
                agent_wallet=attestation.agent_wallet,
                verifier_status=attestation.status,
                verifier_score=(
                    round(attestation.score, 6) if credit_eligible else 0.0
                ),
                credit_eligible=credit_eligible,
                reputation_points=_points_for_attestation(
                    attestation,
                    credit_eligible=credit_eligible,
                ),
                reason=_reason_for_attestation(
                    attestation,
                    credit_eligible=credit_eligible,
                ),
            )
        )
    return updates


def build_reputation_leaderboard(
    updates: Iterable[ReputationUpdate | dict[str, object]],
) -> list[ReputationLedgerEntry]:
    aggregates: dict[tuple[str, str], dict[str, float | int | str]] = {}
    for raw_update in updates:
        update = _coerce_update(raw_update)
        if update.verifier_status == "accepted" and not update.credit_eligible:
            continue
        key = (update.node_role, update.peer_id)
        aggregate = aggregates.setdefault(
            key,
            {
                "node_role": update.node_role,
                "peer_id": update.peer_id,
                "reputation_points": 0.0,
                "accepted_contributions": 0,
                "rejected_contributions": 0,
                "total_verifier_score": 0.0,
            },
        )
        aggregate["reputation_points"] = round(
            float(aggregate["reputation_points"]) + update.reputation_points,
            6,
        )
        if update.verifier_status == "accepted":
            aggregate["accepted_contributions"] = (
                int(aggregate["accepted_contributions"]) + 1
            )
            aggregate["total_verifier_score"] = round(
                float(aggregate["total_verifier_score"]) + update.verifier_score,
                6,
            )
        elif update.verifier_status == "rejected":
            aggregate["rejected_contributions"] = (
                int(aggregate["rejected_contributions"]) + 1
            )

    return sorted(
        (
            ReputationLedgerEntry(
                node_role=str(aggregate["node_role"]),
                peer_id=str(aggregate["peer_id"]),
                reputation_points=float(aggregate["reputation_points"]),
                accepted_contributions=int(aggregate["accepted_contributions"]),
                rejected_contributions=int(aggregate["rejected_contributions"]),
                total_verifier_score=float(aggregate["total_verifier_score"]),
            )
            for aggregate in aggregates.values()
        ),
        key=lambda entry: (
            -entry.reputation_points,
            entry.node_role,
            entry.peer_id,
        ),
    )


def _credit_eligible(attestation: VerificationAttestation) -> bool:
    return bool(
        attestation.status == "accepted"
        and attestation.signer
        and attestation.agent_wallet
        and attestation.output_hash
        and attestation.signer.lower() == attestation.agent_wallet.lower()
    )


def _points_for_attestation(
    attestation: VerificationAttestation,
    *,
    credit_eligible: bool,
) -> float:
    if not credit_eligible:
        return 0.0
    return round(attestation.score * 100.0, 6)


def _reason_for_attestation(
    attestation: VerificationAttestation,
    *,
    credit_eligible: bool,
) -> str:
    if credit_eligible:
        return "verifier_score_credit"
    if attestation.status != "accepted":
        return "no_credit_for_rejected_verifier_status"
    if (
        attestation.signer
        and attestation.agent_wallet
        and attestation.signer.lower() != attestation.agent_wallet.lower()
    ):
        return "no_credit_for_signer_wallet_mismatch"
    return "no_credit_without_verified_execution_signer"


def _coerce_update(update: ReputationUpdate | dict[str, object]) -> ReputationUpdate:
    if isinstance(update, ReputationUpdate):
        return update
    return ReputationUpdate(
        job_id=str(update["job_id"]),
        node_role=str(update["node_role"]),
        peer_id=str(update["peer_id"]),
        agent_wallet=(
            str(update["agent_wallet"]) if update.get("agent_wallet") else None
        ),
        verifier_status=str(update["verifier_status"]),
        verifier_score=float(update["verifier_score"]),
        credit_eligible=bool(update.get("credit_eligible", False)),
        reputation_points=float(update["reputation_points"]),
        reason=str(update["reason"]),
    )
