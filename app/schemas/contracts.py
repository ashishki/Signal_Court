"""Core request and response contracts for Signal Count."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ThesisRequest(BaseModel):
    thesis: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    horizon_days: int = Field(gt=0)


class ScenarioView(BaseModel):
    bull: float
    base: float
    bear: float


class ProvenanceRecord(BaseModel):
    node_role: str = Field(min_length=1)
    peer_id: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)


class SpecialistResponse(BaseModel):
    job_id: str = Field(min_length=1)
    node_role: str = Field(min_length=1)
    peer_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    scenario_view: ScenarioView
    signals: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[str] = Field(default_factory=list)
    timestamp: str = Field(min_length=1)
    agent_wallet: str | None = Field(default=None, pattern=r"^0x[a-fA-F0-9]{40}$")
    ree_receipt_hash: str | None = None
    receipt_status: str | None = None
    ree_prompt_hash: str | None = None
    ree_tokens_hash: str | None = None
    ree_model_name: str | None = None
    ree_receipt_body: dict[str, Any] | None = None
    ree_receipt_path: str | None = None


class TaskSpec(BaseModel):
    job_id: str = Field(min_length=1)
    thesis: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    horizon_days: int = Field(gt=0)


class AgentIdentity(BaseModel):
    role: str = Field(min_length=1)
    peer_id: str = Field(min_length=1)
    wallet: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")


class SignatureEnvelope(BaseModel):
    signer: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")
    task_hash: str = Field(pattern=r"^0x[a-fA-F0-9]{64}$")
    output_hash: str = Field(pattern=r"^0x[a-fA-F0-9]{64}$")
    signature: str = Field(pattern=r"^0x[a-fA-F0-9]{130}$")
    algorithm: str = "eip191"


class SignedAgentExecution(BaseModel):
    task: TaskSpec
    identity: AgentIdentity
    response: SpecialistResponse
    signature: SignatureEnvelope


class VerificationAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    node_role: str = Field(min_length=1)
    peer_id: str = Field(min_length=1)
    status: str = Field(pattern=r"^(accepted|rejected)$")
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    signer: str | None = None
    agent_wallet: str | None = Field(default=None, pattern=r"^0x[a-fA-F0-9]{40}$")
    output_hash: str | None = None
    ree_receipt_hash: str | None = None
    receipt_status: str | None = None
    ree_prompt_hash: str | None = None
    ree_tokens_hash: str | None = None
    ree_model_name: str | None = None
    ree_receipt_body: dict[str, Any] | None = None
    ree_receipt_path: str | None = None
    verifier: str | None = None
    attestation_hash: str | None = None
    verifier_signature: str | None = None
    signature_algorithm: str | None = None


class MemoEvidenceSource(BaseModel):
    text: str = Field(min_length=1)
    source_role: str = Field(min_length=1)
    peer_id: str = Field(min_length=1)
    output_hash: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None
    source_hash: str | None = None
    source_quality: str | None = None


class FinalMemo(BaseModel):
    job_id: str = Field(min_length=1)
    normalized_thesis: str = Field(min_length=1)
    scenarios: ScenarioView
    supporting_evidence: list[str] = Field(default_factory=list)
    opposing_evidence: list[str] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation_triggers: list[str] = Field(default_factory=list)
    confidence_rationale: str = ""
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    evidence_sources: list[MemoEvidenceSource] = Field(default_factory=list)
    verification_attestations: list[VerificationAttestation] = Field(
        default_factory=list
    )
    partial: bool = False
    partial_reason: str | None = None
