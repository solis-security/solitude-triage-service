from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.es_client import MAX_TRIAGE_DOCS, audit_index, scan_all, signin_index
from app.evidence import build_evidence_index, hydrate_findings
from app.models import AnalysisInput, Finding, FindingAnalysisInput, TriageAnswer, TriageReport
from app.rules import (
    MAX_FINDINGS_PER_RULE_SUBJECT,
    MAX_FINDINGS_TOTAL,
    cap_findings,
    run_all_rules,
    summarize_triage,
)

router = APIRouter(prefix="/triage", tags=["triage"])


@router.get("/{case_id}", response_model=TriageReport)
def get_triage_report(
    case_id: str,
    tenant_domain: str | None = Query(None, description="Tenant's primary mail domain(s), comma-separated"),
):
    signins, signins_truncated = scan_all(signin_index(case_id))
    audit_records, audit_truncated = scan_all(audit_index(case_id))

    tenant_domains = [d.strip() for d in tenant_domain.split(",")] if tenant_domain else None
    raw_findings, dropped_findings = cap_findings(
        run_all_rules(signins, audit_records, tenant_domains)
    )

    findings = [
        Finding(
            id=f["id"],
            rule=f["rule"], severity=f["severity"], area=f["area"], text=f["text"],
            evidence=f["evidence"], subject=f.get("subject"),
        )
        for f in raw_findings
    ]

    summary = summarize_triage(raw_findings)
    answers = [TriageAnswer(**a) for a in summary["answers"]]

    limitations = [
        "This is a limited-scope triage assessment, not a full forensic investigation.",
        "Only ingested sign-in and audit log data was analysed; mailbox content was not reviewed.",
    ]
    if not tenant_domains:
        limitations.append(
            "No tenant domain was supplied — external-forwarding detection could not confirm which "
            "destination domains are external to the tenant."
        )
    if dropped_findings:
        limitations.append(
            f"{dropped_findings:,} finding(s) were omitted to bound this report's size: at most "
            f"{MAX_FINDINGS_PER_RULE_SUBJECT} per rule per account, and {MAX_FINDINGS_TOTAL:,} in "
            "total. The accounts and rules involved are still represented."
        )
    if signins_truncated or audit_truncated:
        which = " and ".join(
            n for n, t in (("sign-in", signins_truncated), ("audit", audit_truncated)) if t
        )
        limitations.append(
            f"Only the earliest {MAX_TRIAGE_DOCS:,} {which} records by timestamp were analysed — "
            "this case exceeds the per-triage document ceiling, so findings may be incomplete."
        )

    return TriageReport(
        case_id=case_id,
        tenant_domain=tenant_domain,
        generated_at=datetime.now(timezone.utc),
        findings=findings,
        likely_compromised_accounts=summary["likely_compromised_accounts"],
        answers=answers,
        limitations=limitations,
    )


@router.get("/{case_id}/findings", response_model=list[Finding])
def get_findings(case_id: str, tenant_domain: str | None = Query(None)):
    return get_triage_report(case_id, tenant_domain).findings


@router.get("/{case_id}/analysis-input", response_model=AnalysisInput)
def get_analysis_input(
    case_id: str,
    tenant_domain: str | None = Query(None, description="Tenant's primary mail domain(s), comma-separated"),
    limit: int = Query(200, ge=1, le=MAX_FINDINGS_TOTAL,
                       description="Maximum findings returned; the rest are reported in limitations"),
):
    """Findings with their evidence resolved into `{id, source, summary}`.

    This is the bridge to the AI analysis engine. Findings reference
    Elasticsearch document ids, while the analysis tools require evidence
    records they can actually read, and grounding validation is only as good
    as the summaries it validates against — so the resolution happens here,
    against the real records, rather than being left to the caller.

    The response carries limitations as well as findings. summarize_case
    writes an executive narrative over whatever it is handed, so a caller
    that cannot tell a complete case from a truncated one would report a
    partial picture with full confidence.
    """
    signins, signins_truncated = scan_all(signin_index(case_id))
    audit_records, audit_truncated = scan_all(audit_index(case_id))

    tenant_domains = [d.strip() for d in tenant_domain.split(",")] if tenant_domain else None
    findings, dropped = cap_findings(run_all_rules(signins, audit_records, tenant_domains))

    limitations: list[str] = []
    if signins_truncated or audit_truncated:
        which = " and ".join(
            n for n, tr in (("sign-in", signins_truncated), ("audit", audit_truncated)) if tr
        )
        limitations.append(
            f"Only the earliest {MAX_TRIAGE_DOCS:,} {which} records by timestamp were analysed — "
            "this case exceeds the per-triage document ceiling, so findings may be incomplete."
        )
    if dropped:
        limitations.append(
            f"{dropped:,} repeated finding(s) were omitted to bound report size. The accounts "
            "and rules involved are still represented."
        )

    # Bound what a caller can hand to summarize_case: that prompt serialises
    # every finding, so an unbounded list silently overruns the model's
    # context and returns a summary grounded in an arbitrary prefix.
    if len(findings) > limit:
        limitations.append(
            f"{len(findings) - limit:,} further finding(s) "
            f"were not returned: this response is capped at {limit}. Raise `limit` or analyse in "
            "batches; a summary over this subset does not describe the whole case."
        )
        findings = findings[:limit]

    cited_ids = {doc_id for f in findings for doc_id in f.get("evidence", [])}
    evidence_index = build_evidence_index(signins, audit_records, only_ids=cited_ids)
    return AnalysisInput(
        case_id=case_id,
        findings=[FindingAnalysisInput(**f) for f in hydrate_findings(findings, evidence_index)],
        limitations=limitations,
    )
