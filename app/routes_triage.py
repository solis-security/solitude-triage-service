from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.es_client import MAX_TRIAGE_DOCS, audit_index, scan_all, signin_index
from app.models import Finding, TriageAnswer, TriageReport
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
