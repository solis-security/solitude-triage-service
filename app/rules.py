"""Triage rule engine.

Every function here is pure: it takes already-fetched log records (plain
dicts, as returned from Elasticsearch) and returns a list of Finding-shaped
dicts. Keeping ES I/O out of this module means the detection logic can be
unit tested with synthetic data and no running cluster.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from itertools import combinations

from app.config import settings

# Rough centroid coordinates for a handful of countries, used only to
# approximate travel distance for the impossible-travel heuristic. Not
# geodesically precise — sufficient for flagging implausible sign-in pairs.
COUNTRY_CENTROIDS: dict[str, tuple[float, float]] = {
    "US": (39.8, -98.6), "GB": (54.0, -2.0), "NG": (9.1, 8.7),
    "RU": (61.5, 105.3), "CN": (35.9, 104.2), "DE": (51.2, 10.5),
    "FR": (46.2, 2.2), "IN": (20.6, 79.0), "BR": (-14.2, -51.9),
    "CA": (56.1, -106.3), "AU": (-25.3, 133.8), "ZA": (-30.6, 22.9),
    "UA": (48.4, 31.2), "VN": (14.1, 108.3), "IE": (53.4, -8.2),
    "NL": (52.1, 5.3), "SG": (1.35, 103.8), "AE": (23.4, 53.8),
}


def _parse_ts(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def detect_impossible_travel(signins: list[dict]) -> list[dict]:
    """Flag pairs of successful sign-ins, same user, different countries,
    where the implied travel speed exceeds a realistic threshold."""
    findings = []
    by_user: dict[str, list[dict]] = defaultdict(list)
    for s in signins:
        if s.get("status") == "success":
            by_user[s["user_principal_name"]].append(s)

    for user, events in by_user.items():
        events = sorted(events, key=lambda e: _parse_ts(e["timestamp"]))
        for a, b in combinations(events, 2):
            if a["location_country"] == b["location_country"]:
                continue
            ca, cb = a["location_country"], b["location_country"]
            if ca not in COUNTRY_CENTROIDS or cb not in COUNTRY_CENTROIDS:
                continue
            hours = abs((_parse_ts(b["timestamp"]) - _parse_ts(a["timestamp"])).total_seconds()) / 3600
            if hours == 0:
                hours = 0.01
            distance = _haversine_km(COUNTRY_CENTROIDS[ca], COUNTRY_CENTROIDS[cb])
            required_speed = distance / hours
            if required_speed > settings.impossible_travel_kmh_threshold:
                findings.append({
                    "rule": "impossible_travel",
                    "severity": "high",
                    "area": "Authentication and sign-ins",
                    "text": (
                        f"{user}: sign-in from {ca} then {cb} within "
                        f"{hours:.1f}h — implies ~{required_speed:.0f} km/h travel, "
                        "exceeding plausible travel speed."
                    ),
                    "evidence": [a["_id"], b["_id"]],
                    "subject": user,
                })
    return findings


def detect_risky_signin_flags(signins: list[dict]) -> list[dict]:
    """Flag sign-ins Entra ID itself already scored medium/high risk."""
    findings = []
    for s in signins:
        if s.get("status") == "success" and s.get("risk_level") in ("medium", "high"):
            findings.append({
                "rule": "risky_signin_flag",
                "severity": "high" if s["risk_level"] == "high" else "medium",
                "area": "Authentication and sign-ins",
                "text": (
                    f"{s['user_principal_name']}: sign-in from {s['ip_address']} "
                    f"({s['location_country']}) flagged {s['risk_level']} risk by Entra ID."
                ),
                "evidence": [s["_id"]],
                "subject": s["user_principal_name"],
            })
    return findings


def detect_legacy_auth(signins: list[dict]) -> list[dict]:
    findings = []
    for s in signins:
        if s.get("status") == "success" and (
            s.get("client_app") in settings.legacy_auth_clients or s.get("auth_protocol") == "basic"
        ):
            findings.append({
                "rule": "legacy_auth",
                "severity": "medium",
                "area": "Authentication and sign-ins",
                "text": (
                    f"{s['user_principal_name']}: successful sign-in via legacy/basic auth "
                    f"client '{s['client_app']}' — not covered by modern-auth Conditional Access."
                ),
                "evidence": [s["_id"]],
                "subject": s["user_principal_name"],
            })
    return findings


_INBOX_RULE_OPS = {"New-InboxRule", "Set-InboxRule", "New-TransportRule", "Set-TransportRule"}


def detect_suspicious_mail_rules(audit_records: list[dict], tenant_domains: list[str] | None = None) -> list[dict]:
    """Flag inbox/transport rules that forward or redirect mail externally,
    or that silently delete messages (often used to hide fraud replies)."""
    tenant_domains = [d.lower() for d in (tenant_domains or [])]
    findings = []
    for r in audit_records:
        if r.get("operation") not in _INBOX_RULE_OPS:
            continue
        params = r.get("parameters", {}) or {}
        forward_to = params.get("ForwardTo") or params.get("RedirectTo") or params.get("ForwardAsAttachmentTo")
        delete_message = bool(params.get("DeleteMessage"))

        if forward_to:
            domain = str(forward_to).split("@")[-1].lower()
            external = bool(tenant_domains) and domain not in tenant_domains
            findings.append({
                "rule": "suspicious_mail_rule",
                "severity": "high" if external or not tenant_domains else "medium",
                "area": "Mail rules and forwarding",
                "text": (
                    f"{r['user_principal_name']}: {r['operation']} forwards/redirects mail to "
                    f"{forward_to}" + (" (external domain)" if external else "") + "."
                ),
                "evidence": [r["_id"]],
                "subject": r["user_principal_name"],
            })
        if delete_message:
            findings.append({
                "rule": "suspicious_mail_rule_delete",
                "severity": "high",
                "area": "Mail rules and forwarding",
                "text": (
                    f"{r['user_principal_name']}: {r['operation']} silently deletes matching "
                    "messages — a common technique to hide fraudulent reply traffic."
                ),
                "evidence": [r["_id"]],
                "subject": r["user_principal_name"],
            })
    return findings


def detect_risky_app_consent(audit_records: list[dict]) -> list[dict]:
    findings = []
    for r in audit_records:
        if r.get("operation") != "Consent to application":
            continue
        params = r.get("parameters", {}) or {}
        scopes = params.get("scopes", []) or params.get("Scope", "").split()
        is_admin_consent = bool(params.get("IsAdminConsent", False))
        risky = [s for s in scopes if s in settings.risky_consent_scopes]
        if risky and not is_admin_consent:
            findings.append({
                "rule": "risky_app_consent",
                "severity": "medium",
                "area": "Applications and access",
                "text": (
                    f"{r['user_principal_name']}: granted non-admin consent to application "
                    f"'{params.get('AppDisplayName', params.get('ClientAppId', 'unknown'))}' "
                    f"with high-impact scope(s): {', '.join(risky)}."
                ),
                "evidence": [r["_id"]],
                "subject": r["user_principal_name"],
            })
    return findings


def run_all_rules(signins: list[dict], audit_records: list[dict], tenant_domains: list[str] | None = None) -> list[dict]:
    findings: list[dict] = []
    findings += detect_impossible_travel(signins)
    findings += detect_risky_signin_flags(signins)
    findings += detect_legacy_auth(signins)
    findings += detect_suspicious_mail_rules(audit_records, tenant_domains)
    findings += detect_risky_app_consent(audit_records)
    return findings


def summarize_triage(findings: list[dict]) -> dict:
    """Build the triage-question answers from a finding list, mirroring the
    Triage Assessment Module's fixed question set."""
    compromised = sorted({f["subject"] for f in findings if f["subject"] and f["severity"] in ("high", "medium")})

    mail_findings = [f for f in findings if f["area"] == "Mail rules and forwarding"]
    signin_findings = [f for f in findings if f["area"] == "Authentication and sign-ins"]
    high_severity = [f for f in findings if f["severity"] == "high"]

    def basis(fs: list[dict]) -> list[str]:
        return [f"{f['rule']}:{','.join(f['evidence'])}" for f in fs]

    answers = []

    if compromised:
        answers.append({
            "question": "Which accounts are likely compromised?",
            "answer": f"{', '.join(compromised)} — based on {len(signin_findings) + len(mail_findings)} supporting finding(s).",
            "basis": basis(signin_findings + mail_findings),
        })
    else:
        answers.append({
            "question": "Which accounts are likely compromised?",
            "answer": "No account meets the triage threshold for likely compromise based on ingested logs.",
            "basis": [],
        })

    if mail_findings:
        answers.append({
            "question": "What data may be at risk?",
            "answer": (
                "Mailbox content for the affected account(s) during the period the mail rule(s) "
                "were active. Full content review was not performed — this is a limited-log triage."
            ),
            "basis": basis(mail_findings),
        })
    else:
        answers.append({
            "question": "What data may be at risk?",
            "answer": "No forwarding/redirect/delete mail rules were found in the ingested logs.",
            "basis": [],
        })

    legal = any(f["rule"] in ("suspicious_mail_rule", "suspicious_mail_rule_delete") for f in mail_findings)
    answers.append({
        "question": "Is legal support recommended?",
        "answer": "Yes — evidence of external mail forwarding or message deletion was found." if legal
        else "Not indicated by triage-scope logs alone.",
        "basis": basis(mail_findings) if legal else [],
    })

    further = len(high_severity) >= 1 or len(findings) >= 3
    answers.append({
        "question": "Is a full forensic investigation recommended?",
        "answer": "Recommended — establish full scope of accessed data and confirm no other accounts were touched." if further
        else "Not indicated based on current triage-scope findings.",
        "basis": basis(high_severity) if further else [],
    })

    return {"likely_compromised_accounts": compromised, "answers": answers}
