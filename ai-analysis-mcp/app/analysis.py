from __future__ import annotations

from app import prompts
from app.audit import append_audit_record, read_recent_validations
from app.config import settings
from app.ollama_client import OllamaClient, OllamaUnavailableError
from app.schemas import AnalysisResult, CaseSummaryResult, ContentSensitivityResult, EngineHealth
from app.validation import compute_engine_health, validate_grounding


def _record_and_return(kind: str, result_dict: dict, provided_evidence_ids: list[str] | None, model: str, digest: str | None) -> dict:
    append_audit_record({
        "kind": kind,
        "model": model,
        "model_digest": digest,
        "validation": result_dict["validation"],
        "evidence_refs": result_dict.get("evidence_refs", []),
    })
    return result_dict


def analyze_finding(finding: dict, client: OllamaClient | None = None) -> AnalysisResult:
    client = client or OllamaClient()
    evidence_ids = [e["id"] for e in finding["evidence"]]

    try:
        raw = client.generate_json(
            prompts.FINDING_ANALYSIS_SYSTEM,
            prompts.finding_analysis_user_prompt(finding),
        )
        insufficient = bool(raw.get("insufficient_evidence", False))
        refs = list(raw.get("evidence_refs", []))
        validation = validate_grounding(refs, evidence_ids, insufficient)
        result = AnalysisResult(
            narrative=raw.get("narrative", ""),
            confidence=raw.get("confidence", "low"),
            evidence_refs=refs if validation == "grounded" else [],
            insufficient_evidence=insufficient,
            model=client.model,
            model_digest=client.model_digest(),
            validation=validation,
        )
    except OllamaUnavailableError as e:
        result = AnalysisResult(
            narrative="Analysis unavailable — the AI engine could not be reached or returned an unusable response.",
            confidence="low",
            evidence_refs=[],
            insufficient_evidence=True,
            model=client.model,
            model_digest=None,
            validation="engine_error",
            error=str(e),
        )

    _record_and_return("finding_analysis", result.model_dump(), evidence_ids, result.model, result.model_digest)
    return result


def summarize_case(findings: list[dict], client: OllamaClient | None = None) -> CaseSummaryResult:
    client = client or OllamaClient()
    all_evidence_ids = [e["id"] for f in findings for e in f["evidence"]]
    high_severity_count = sum(1 for f in findings if f["severity"] == "high")

    try:
        raw = client.generate_json(
            prompts.CASE_SUMMARY_SYSTEM,
            prompts.case_summary_user_prompt(findings),
        )
        insufficient = bool(raw.get("insufficient_evidence", False))
        refs = list(raw.get("evidence_refs", []))
        validation = validate_grounding(refs, all_evidence_ids, insufficient)
        result = CaseSummaryResult(
            narrative=raw.get("narrative", ""),
            confidence=raw.get("confidence", "low"),
            evidence_refs=refs if validation == "grounded" else [],
            insufficient_evidence=insufficient,
            model=client.model,
            model_digest=client.model_digest(),
            validation=validation,
            finding_count=len(findings),
            high_severity_count=high_severity_count,
        )
    except OllamaUnavailableError as e:
        result = CaseSummaryResult(
            narrative="Executive summary unavailable — the AI engine could not be reached or returned an unusable response.",
            confidence="low",
            evidence_refs=[],
            insufficient_evidence=True,
            model=client.model,
            model_digest=None,
            validation="engine_error",
            error=str(e),
            finding_count=len(findings),
            high_severity_count=high_severity_count,
        )

    _record_and_return("case_summary", result.model_dump(), all_evidence_ids, result.model, result.model_digest)
    return result


def analyze_email_content(evidence_id: str, subject: str, body: str | None = None, client: OllamaClient | None = None) -> ContentSensitivityResult:
    client = client or OllamaClient()

    try:
        raw = client.generate_json(
            prompts.CONTENT_SENSITIVITY_SYSTEM,
            prompts.content_sensitivity_user_prompt(subject, body),
        )
        method = raw.get("method", "subject_line_fallback" if not body else "content_analysis")
        result = ContentSensitivityResult(
            evidence_id=evidence_id,
            method=method,
            sensitivity_flags=list(raw.get("sensitivity_flags", [])),
            narrative=raw.get("narrative", ""),
            confidence=raw.get("confidence", "low"),
            model=client.model,
            model_digest=client.model_digest(),
            validation="grounded",
        )
    except OllamaUnavailableError as e:
        result = ContentSensitivityResult(
            evidence_id=evidence_id,
            method="subject_line_fallback" if not body else "content_analysis",
            sensitivity_flags=[],
            narrative="Content sensitivity analysis unavailable — the AI engine could not be reached or returned an unusable response.",
            confidence="low",
            model=client.model,
            model_digest=None,
            validation="engine_error",
            error=str(e),
        )

    _record_and_return("content_sensitivity", result.model_dump(), [evidence_id], result.model, result.model_digest)
    return result


def get_engine_health(client: OllamaClient | None = None) -> EngineHealth:
    client = client or OllamaClient()
    reachable, models = client.is_reachable()
    recent = read_recent_validations(settings.circuit_breaker_window)
    health = compute_engine_health(recent, settings.circuit_breaker_window, settings.circuit_breaker_rejection_threshold)
    return EngineHealth(
        ollama_reachable=reachable,
        available_models=models,
        **health,
    )
