"""Generate realistic-looking mock M365 sign-in and audit logs for local
testing of the triage service. Writes newline-delimited JSON (.jsonl),
which can be POSTed to /ingest/{case_id}/file.

Usage:
    python scripts/generate_sample_logs.py --case-id SR-2026-0501 --out-dir sample_data
"""

from __future__ import annotations

import argparse
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

USERS = ["a.morales", "d.farrow", "j.oyelaran", "m.chen", "s.patel"]
NORMAL_COUNTRIES = ["US", "GB", "CA"]
ATTACKER_COUNTRIES = ["NG", "RU", "VN"]
CLIENT_APPS_MODERN = ["Browser", "Mobile Apps and Desktop clients"]
CLIENT_APPS_LEGACY = ["Authenticated SMTP", "Other clients", "IMAP4"]


def rand_ip(country_hint: str) -> str:
    return f"{random.randint(1, 223)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"


def gen_signins(start: datetime, compromised_user: str) -> list[dict]:
    events = []
    t = start
    # Each user has a single consistent home country for their normal
    # activity — real users don't hop countries between ordinary sign-ins,
    # and generating one at random per event would flood the impossible-
    # travel rule with false positives for every account.
    home_country = {user: random.choice(NORMAL_COUNTRIES) for user in USERS}

    for _ in range(40):
        user = random.choice(USERS)
        t += timedelta(minutes=random.randint(5, 90))
        events.append({
            "id": str(uuid.uuid4()),
            "timestamp": t.isoformat(),
            "user_principal_name": f"{user}@contoso.onmicrosoft.com",
            "ip_address": rand_ip("US"),
            "location_country": home_country[user],
            "device": "corp-laptop",
            "client_app": random.choice(CLIENT_APPS_MODERN),
            "auth_protocol": "modern",
            "status": "success",
            "risk_level": "none",
            "conditional_access_status": "success",
        })

    # The compromise: attacker sign-in from an unusual country shortly after
    # a legitimate one, plus a follow-up legacy-auth sign-in.
    legit_time = t + timedelta(hours=1)
    events.append({
        "id": str(uuid.uuid4()),
        "timestamp": legit_time.isoformat(),
        "user_principal_name": f"{compromised_user}@contoso.onmicrosoft.com",
        "ip_address": rand_ip("US"),
        "location_country": home_country[compromised_user],
        "device": "corp-laptop",
        "client_app": "Browser",
        "auth_protocol": "modern",
        "status": "success",
        "risk_level": "none",
        "conditional_access_status": "success",
    })
    attacker_time = legit_time + timedelta(minutes=25)
    events.append({
        "id": str(uuid.uuid4()),
        "timestamp": attacker_time.isoformat(),
        "user_principal_name": f"{compromised_user}@contoso.onmicrosoft.com",
        "ip_address": rand_ip("NG"),
        "location_country": random.choice(ATTACKER_COUNTRIES),
        "device": "unknown",
        "client_app": "Browser",
        "auth_protocol": "modern",
        "status": "success",
        "risk_level": "high",
        "conditional_access_status": "success",
    })
    legacy_time = attacker_time + timedelta(minutes=10)
    events.append({
        "id": str(uuid.uuid4()),
        "timestamp": legacy_time.isoformat(),
        "user_principal_name": f"{compromised_user}@contoso.onmicrosoft.com",
        "ip_address": rand_ip("NG"),
        "location_country": random.choice(ATTACKER_COUNTRIES),
        "device": "unknown",
        "client_app": "Authenticated SMTP",
        "auth_protocol": "basic",
        "status": "success",
        "risk_level": "medium",
        "conditional_access_status": "success",
    })
    return events


def gen_audit(start: datetime, compromised_user: str) -> list[dict]:
    events = []
    t = start + timedelta(hours=1, minutes=40)
    upn = f"{compromised_user}@contoso.onmicrosoft.com"

    events.append({
        "id": str(uuid.uuid4()),
        "timestamp": t.isoformat(),
        "operation": "New-InboxRule",
        "user_principal_name": upn,
        "workload": "Exchange",
        "parameters": {
            "Name": "Update",
            "ForwardTo": "[email protected]",
            "DeleteMessage": True,
        },
        "result_status": "success",
    })

    t += timedelta(minutes=15)
    events.append({
        "id": str(uuid.uuid4()),
        "timestamp": t.isoformat(),
        "operation": "Consent to application",
        "user_principal_name": upn,
        "workload": "AzureActiveDirectory",
        "parameters": {
            "AppDisplayName": "QuickReports Sync",
            "scopes": ["Mail.Read", "offline_access"],
            "IsAdminConsent": False,
        },
        "result_status": "success",
    })

    # Some benign background audit activity
    for _ in range(10):
        u = random.choice(USERS)
        t += timedelta(minutes=random.randint(10, 60))
        events.append({
            "id": str(uuid.uuid4()),
            "timestamp": t.isoformat(),
            "operation": random.choice(["Set-Mailbox", "UserLoggedIn", "FileAccessed"]),
            "user_principal_name": f"{u}@contoso.onmicrosoft.com",
            "workload": random.choice(["Exchange", "SharePoint"]),
            "parameters": {},
            "result_status": "success",
        })
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-id", default="SR-2026-0501")
    ap.add_argument("--out-dir", default="sample_data")
    ap.add_argument("--compromised-user", default="d.farrow")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    start = datetime.now(timezone.utc) - timedelta(days=1)
    signins = gen_signins(start, args.compromised_user)
    audit = gen_audit(start, args.compromised_user)

    signin_path = out_dir / f"{args.case_id}-signin.jsonl"
    audit_path = out_dir / f"{args.case_id}-audit.jsonl"
    signin_path.write_text("\n".join(json.dumps(e) for e in signins))
    audit_path.write_text("\n".join(json.dumps(e) for e in audit))

    print(f"Wrote {len(signins)} sign-in events -> {signin_path}")
    print(f"Wrote {len(audit)} audit events -> {audit_path}")
    print()
    print("Ingest with:")
    print(f"  curl -X POST 'http://localhost:8000/ingest/{args.case_id}/file?log_type=signin' -F 'file=@{signin_path}'")
    print(f"  curl -X POST 'http://localhost:8000/ingest/{args.case_id}/file?log_type=audit' -F 'file=@{audit_path}'")
    print(f"  curl 'http://localhost:8000/triage/{args.case_id}?tenant_domain=contoso.onmicrosoft.com'")


if __name__ == "__main__":
    main()
