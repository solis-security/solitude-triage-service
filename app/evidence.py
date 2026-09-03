"""Turn raw log records into the compact, model-facing evidence the AI
analysis tools require.

Findings carry Elasticsearch document ids; the analysis engine needs
`{id, source, summary}`. Something has to stand between them, and this is
it. Everything here is pure — plain dicts in, plain dicts out, no
Elasticsearch — so the summaries can be tested exactly like the rules are.

Two rules govern what a summary may contain:

1. Only what is needed to support, or fail to support, a conclusion. The
   model sees these strings and nothing else, so an over-stuffed summary
   both wastes context and widens what a prompt injection could reach.
2. Facts only, in the record's own terms. A summary that characterises
   ("suspicious sign-in from a risky country") pre-empts the judgement the
   analysis is supposed to make, and the grounding gate cannot catch a
   conclusion that was smuggled in through its evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.rules import parse_timestamp
from app.sanitize import as_bool
from app.sanitize import safe_text as _safe

SIGNIN_SOURCE = "Sign-in log"
AUDIT_SOURCE = "Unified Audit Log"

# Audit parameters worth surfacing, and how to phrase them. Anything not
# listed is summarised by name only: a mail rule can carry arbitrary
# operator-supplied strings, and passing those through verbatim would put
# untrusted tenant content directly into the prompt.
_FORWARD_KEYS = ("ForwardTo", "RedirectTo", "ForwardAsAttachmentTo")


def _fmt_ts(value: Any) -> str:
    """Minute precision, genuinely in UTC.

    Slicing the first sixteen characters off the raw string and appending
    "UTC" mislabelled any offset-bearing timestamp: "12:00+05:00" was
    rendered "12:00 UTC", five hours out. The rule engine normalises
    properly, so the finding said one time and the evidence backing it said
    another — and the model was asked to ground a travel-time conclusion on
    the contradiction. Same parser as the rules, so the two cannot diverge.
    """
    if value is None:
        return "unknown time"
    try:
        return parse_timestamp(value).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return _safe(value, 32)


def summarize_signin(doc: dict) -> str:
    upn = _safe(doc.get("user_principal_name") or "unknown user")
    status = doc.get("status", "unknown")
    outcome = "Successful" if status == "success" else "Failed"
    country = _safe(doc.get("location_country") or "unknown country", 32)
    ip = _safe(doc.get("ip_address") or "unknown IP", 45)
    client = _safe(doc.get("client_app") or "unknown client", 48)
    protocol = _safe(doc.get("auth_protocol") or "unknown", 16)
    risk = _safe(doc.get("risk_level") or "none", 16)

    parts = [
        f"{outcome} sign-in by {upn} from {country} ({ip}) "
        f"using {client} over {protocol} auth at {_fmt_ts(doc.get('timestamp'))}."
    ]
    if risk and risk != "none":
        parts.append(f"Entra ID scored this sign-in {risk} risk.")
    ca = doc.get("conditional_access_status")
    if ca and ca != "success":
        parts.append(f"Conditional Access status: {_safe(ca, 48)}.")
    return " ".join(parts)


def summarize_audit(doc: dict) -> str:
    upn = _safe(doc.get("user_principal_name") or "unknown user")
    operation = _safe(doc.get("operation") or "unknown operation", 48)
    workload = _safe(doc.get("workload") or "unknown workload", 48)
    params = doc.get("parameters") or {}

    parts = [
        f"{operation} performed by {upn} in {workload} at "
        f"{_fmt_ts(doc.get('timestamp'))}."
    ]
    if doc.get("result_status") and doc["result_status"] != "success":
        parts.append(f"Result: {_safe(doc['result_status'], 32)}.")

    for key in _FORWARD_KEYS:
        if params.get(key):
            parts.append(f"{key} is set on this rule.")
    if as_bool(params.get("DeleteMessage")):
        parts.append("The rule deletes matching messages.")

    scopes = params.get("scopes") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    if not scopes and params.get("Scope"):
        scopes = str(params["Scope"]).split()
    if scopes:
        parts.append(f"Scopes granted: {_safe(', '.join(str(s) for s in scopes), 200)}.")
        parts.append(
            "Admin consent: yes." if as_bool(params.get("IsAdminConsent")) else "Admin consent: no."
        )
    if params.get("AppDisplayName"):
        # Attacker-choosable: registering an app means naming it.
        parts.append(f'Application name (tenant-supplied text): "{_safe(params["AppDisplayName"])}".')

    named = set(_FORWARD_KEYS) | {"DeleteMessage", "scopes", "Scope", "IsAdminConsent", "AppDisplayName"}
    other = sorted(k for k in params if k not in named)
    if other:
        # Names only, never values.
        parts.append(f"Other parameters present: {_safe(', '.join(other), 200)}.")
    return " ".join(parts)


def build_evidence_index(
    signins: list[dict],
    audit_records: list[dict],
    only_ids: set[str] | None = None,
) -> dict[str, dict]:
    """Map Elasticsearch document id -> {id, source, summary}.

    `only_ids` restricts the work to the ids actually cited. A triage can
    fetch up to the document ceiling per log type while far fewer records
    are ever referenced, and summarising the rest builds tens of thousands
    of strings that are discarded immediately.
    """
    index: dict[str, dict] = {}
    for doc, source, summarize in (
        (signins, SIGNIN_SOURCE, summarize_signin),
        (audit_records, AUDIT_SOURCE, summarize_audit),
    ):
        for record in doc:
            doc_id = record.get("_id")
            if not doc_id or (only_ids is not None and doc_id not in only_ids):
                continue
            index[doc_id] = {"id": doc_id, "source": source, "summary": summarize(record)}
    return index


def hydrate_findings(findings: list[dict], evidence_index: dict[str, dict]) -> list[dict]:
    """Replace each finding's evidence ids with full evidence records.

    An id with no matching record is still emitted, marked as unavailable
    rather than dropped: the analysis engine validates the ids it cites
    against the ids it was given, so silently shrinking that set would let a
    citation look invented when the record merely could not be loaded.
    """
    hydrated = []
    for f in findings:
        items = [
            evidence_index.get(
                doc_id,
                {"id": doc_id, "source": "Unavailable",
                 "summary": "The underlying record could not be loaded for this evidence id."},
            )
            for doc_id in f.get("evidence", [])
        ]
        hydrated.append({
            "id": f["id"],
            "rule": f["rule"],
            "severity": f["severity"],
            "area": f["area"],
            "text": f["text"],
            "evidence": items,
        })
    return hydrated
