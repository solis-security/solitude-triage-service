from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.es_client import audit_index, search_all, signin_index
from app.models import Finding, TriageAnswer, TriageReport
from app.rules import run_all_rules, summarize_triage

router = APIRouter(prefix="/triage", tags=["triage"])


@router.get("/{case_id}", response_model=TriageReport)
def get_triage_report(
    case_id: str,
    tenant_domain: str | None = Query(None, description="Tenant's primary mail domain(s), comma-separated"),
):
    signins = search_all(signin_index(case_id))
    audit_records = search_all(audit_index(case_id))

    tenant_domains = [d.strip() for d in tenant_domain.split(",")] if tenant_domain else None
    raw_findings = run_all_rules(signins, audit_records, tenant_domains)

    findings = [
        Finding(
            id=f"F-{uuid.uuid5(uuid.NAMESPACE_URL, str(i) + str(f['evidence'])).hex[:8]}",
            rule=f["rule"], severity=f["severity"], area=f["area"], text=f["text"],
            evidence=f["evidence"], subject=f.get("subject"),
        )
        for i, f in enumerate(raw_findings)
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
