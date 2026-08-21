from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SignInLog(BaseModel):
    """A single M365 / Entra ID sign-in log entry."""

    id: str
    timestamp: datetime
    user_principal_name: str
    ip_address: str
    location_country: str = Field(..., description="ISO country code, e.g. 'US'")
    device: str | None = None
    client_app: str = Field(..., description="e.g. 'Browser', 'Mobile Apps and Desktop clients', 'Other clients'")
    auth_protocol: Literal["modern", "basic"] = "modern"
    status: Literal["success", "failure"]
    risk_level: Literal["none", "low", "medium", "high"] = "none"
    conditional_access_status: str | None = None


class AuditLogRecord(BaseModel):
    """A single Unified Audit Log record. Covers inbox rule changes,
    application consent grants, and other tenant/mailbox operations."""

    id: str
    timestamp: datetime
    operation: str = Field(..., description="e.g. 'New-InboxRule', 'Consent to application'")
    user_principal_name: str
    workload: str = Field(..., description="e.g. 'Exchange', 'AzureActiveDirectory', 'SharePoint'")
    parameters: dict[str, Any] = Field(default_factory=dict)
    result_status: Literal["success", "failure"] = "success"


class IngestResult(BaseModel):
    case_id: str
    log_type: Literal["signin", "audit"]
    received: int
    indexed: int
    errors: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    id: str
    rule: str
    severity: Literal["low", "medium", "high"]
    area: str
    text: str
    evidence: list[str] = Field(default_factory=list, description="Elasticsearch document ids")
    subject: str | None = Field(None, description="user_principal_name this finding concerns, if any")


class EvidenceItem(BaseModel):
    """One evidence record as the AI analysis engine consumes it. Mirrors
    EvidenceItem in ai-analysis-mcp/src/schemas.ts — the two must stay in
    step, since that server validates against exactly this shape."""

    id: str = Field(..., description="Elasticsearch document id")
    source: str = Field(..., description="e.g. 'Unified Audit Log', 'Sign-in log'")
    summary: str = Field(..., description="Short factual description of what this record shows")


class FindingAnalysisInput(BaseModel):
    """A finding with its evidence resolved, ready to hand to
    analyze_finding / summarize_case."""

    id: str
    rule: str
    severity: Literal["low", "medium", "high"]
    area: str
    text: str
    evidence: list[EvidenceItem]


class AnalysisInput(BaseModel):
    """What the AI analysis engine should be driven from.

    Carries limitations alongside the findings: summarize_case narrates
    whatever it is given, so a caller that cannot distinguish a complete
    case from a truncated one would describe a partial picture with full
    confidence.
    """

    case_id: str
    findings: list[FindingAnalysisInput]
    limitations: list[str] = Field(default_factory=list)


class TriageAnswer(BaseModel):
    question: str
    answer: str
    basis: list[str] = Field(default_factory=list, description="Finding ids supporting this answer")


class TriageReport(BaseModel):
    case_id: str
    tenant_domain: str | None
    generated_at: datetime
    findings: list[Finding]
    likely_compromised_accounts: list[str]
    answers: list[TriageAnswer]
    limitations: list[str]
