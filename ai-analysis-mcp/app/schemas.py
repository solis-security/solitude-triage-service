from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ValidationStatus = Literal["grounded", "rejected_no_evidence", "rejected_ungrounded", "engine_error"]
Confidence = Literal["low", "medium", "high"]


class EvidenceItem(BaseModel):
    """A compact, LLM-facing representation of one evidence record. Keep
    this small and specific — the model should never see more than what it
    needs to support (or fail to support) a conclusion."""

    id: str
    source: str = Field(..., description="e.g. 'Unified Audit Log', 'Sign-in log'")
    summary: str = Field(..., description="Short factual description of what this evidence record shows")


class FindingInput(BaseModel):
    id: str
    rule: str
    severity: Literal["low", "medium", "high"]
    area: str
    text: str
    evidence: list[EvidenceItem]


class AnalysisResult(BaseModel):
    """Common shape for any AI-generated analysis output. Mirrors the AI
    Finding audit trail from the TDD: model/version, evidence refs, and a
    validation status that gates whether this can reach a report."""

    model_config = ConfigDict(protected_namespaces=())

    narrative: str
    confidence: Confidence
    evidence_refs: list[str]
    insufficient_evidence: bool
    model: str
    model_digest: str | None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    validation: ValidationStatus
    error: str | None = None


class CaseSummaryResult(AnalysisResult):
    finding_count: int
    high_severity_count: int


class ContentSensitivityResult(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    evidence_id: str
    method: Literal["content_analysis", "subject_line_fallback"]
    sensitivity_flags: list[str]
    narrative: str
    confidence: Confidence
    model: str
    model_digest: str | None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    validation: ValidationStatus
    error: str | None = None


class EngineHealth(BaseModel):
    window_size: int
    calls_in_window: int
    rejected_in_window: int
    rejection_rate: float
    circuit_breaker_tripped: bool
    ollama_reachable: bool
    available_models: list[str] = Field(default_factory=list)
