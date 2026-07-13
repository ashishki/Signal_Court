"""Deterministic verifier scoring for specialist outputs."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.contracts import SpecialistResponse, TaskSpec


@dataclass(frozen=True)
class ScoreBreakdown:
    schema_validity: float
    task_relevance: float
    evidence_specificity: float
    dissent_value: float
    receipt_strength: float
    latency_completion: float

    @property
    def total(self) -> float:
        return round(
            (self.schema_validity * 0.20)
            + (self.task_relevance * 0.20)
            + (self.evidence_specificity * 0.20)
            + (self.dissent_value * 0.15)
            + (self.receipt_strength * 0.15)
            + (self.latency_completion * 0.10),
            4,
        )


def score_specialist_response(
    response: SpecialistResponse,
    task: TaskSpec,
) -> ScoreBreakdown:
    """Score one structurally valid specialist response on deterministic signals."""
    return ScoreBreakdown(
        schema_validity=1.0,
        task_relevance=_task_relevance(response, task),
        evidence_specificity=_evidence_specificity(response),
        dissent_value=_dissent_value(response),
        receipt_strength=_receipt_strength(response),
        latency_completion=1.0,
    )


def _task_relevance(response: SpecialistResponse, task: TaskSpec) -> float:
    score = 0.0
    if response.job_id == task.job_id:
        score += 0.5
    if response.node_role in {"regime", "narrative", "risk"}:
        score += 0.25
    text = " ".join([response.summary, *response.signals, *response.risks]).lower()
    if task.asset.lower() in text or len(text) >= 80:
        score += 0.25
    return min(score, 1.0)


def _evidence_specificity(response: SpecialistResponse) -> float:
    evidence_items = [
        *response.signals,
        *response.risks,
        *response.citations,
    ]
    if not evidence_items:
        return 0.25 if len(response.summary) >= 80 else 0.0
    non_empty = [item for item in evidence_items if item.strip()]
    density = min(len(non_empty) / 3, 1.0)
    citation_bonus = 0.2 if response.citations else 0.0
    summary_bonus = 0.2 if len(response.summary) >= 80 else 0.0
    return min(density + citation_bonus + summary_bonus, 1.0)


def _dissent_value(response: SpecialistResponse) -> float:
    text = " ".join([response.summary, *response.signals, *response.risks]).lower()
    dissent_markers = (
        "risk",
        "invalid",
        "opposing",
        "downside",
        "break",
        "reversal",
        "contrary",
        "uncertain",
    )
    if response.node_role == "risk":
        return 1.0
    return 1.0 if any(marker in text for marker in dissent_markers) else 0.4


def _receipt_strength(response: SpecialistResponse) -> float:
    if response.receipt_status == "verified":
        return 1.0
    if response.receipt_status == "validated":
        return 0.85
    if response.receipt_status == "parsed":
        return 0.55
    return 0.0
