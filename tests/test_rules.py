from datetime import datetime, timedelta, timezone

from app.rules import (
    detect_impossible_travel,
    detect_legacy_auth,
    detect_risky_app_consent,
    detect_risky_signin_flags,
    detect_suspicious_mail_rules,
    run_all_rules,
    summarize_triage,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)

_counter = iter(range(100000))


def signin(**kwargs):
    base = {
        "_id": "ev-" + str(next(_counter)),
        "timestamp": NOW.isoformat(),
        "user_principal_name": "[email protected]",
        "ip_address": "1.2.3.4",
        "location_country": "US",
        "client_app": "Browser",
        "auth_protocol": "modern",
        "status": "success",
        "risk_level": "none",
    }
    base.update(kwargs)
    return base


def audit(**kwargs):
    base = {
        "_id": "ev-" + str(next(_counter)),
        "timestamp": NOW.isoformat(),
        "operation": "Set-Mailbox",
        "user_principal_name": "[email protected]",
        "workload": "Exchange",
        "parameters": {},
        "result_status": "success",
    }
    base.update(kwargs)
    return base


class TestImpossibleTravel:
    def test_flags_implausible_speed(self):
        a = signin(_id="a1", location_country="US", timestamp=NOW.isoformat())
        b = signin(_id="a2", location_country="NG",
                   timestamp=(NOW + timedelta(minutes=25)).isoformat())
        findings = detect_impossible_travel([a, b])
        assert len(findings) == 1
        assert findings[0]["rule"] == "impossible_travel"
        assert set(findings[0]["evidence"]) == {"a1", "a2"}

    def test_does_not_flag_plausible_travel(self):
        a = signin(_id="a1", location_country="US", timestamp=NOW.isoformat())
        b = signin(_id="a2", location_country="GB",
                   timestamp=(NOW + timedelta(hours=20)).isoformat())
        assert detect_impossible_travel([a, b]) == []

    def test_ignores_failed_signins(self):
        a = signin(_id="a1", location_country="US", status="failure")
        b = signin(_id="a2", location_country="NG",
                   timestamp=(NOW + timedelta(minutes=10)).isoformat(), status="failure")
        assert detect_impossible_travel([a, b]) == []

    def test_ignores_same_country(self):
        a = signin(_id="a1", location_country="US")
        b = signin(_id="a2", location_country="US",
                   timestamp=(NOW + timedelta(minutes=1)).isoformat())
        assert detect_impossible_travel([a, b]) == []

    def test_unknown_country_codes_are_skipped_not_errored(self):
        a = signin(_id="a1", location_country="ZZ")
        b = signin(_id="a2", location_country="US",
                   timestamp=(NOW + timedelta(minutes=1)).isoformat())
        assert detect_impossible_travel([a, b]) == []


class TestRiskySigninFlags:
    def test_flags_high_risk(self):
        s = signin(_id="s1", risk_level="high")
        findings = detect_risky_signin_flags([s])
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"

    def test_ignores_none_risk(self):
        s = signin(_id="s1", risk_level="none")
        assert detect_risky_signin_flags([s]) == []

    def test_medium_risk_is_medium_severity(self):
        s = signin(_id="s1", risk_level="medium")
        findings = detect_risky_signin_flags([s])
        assert findings[0]["severity"] == "medium"


class TestLegacyAuth:
    def test_flags_legacy_client(self):
        s = signin(_id="s1", client_app="Authenticated SMTP", auth_protocol="basic")
        findings = detect_legacy_auth([s])
        assert len(findings) == 1

    def test_ignores_modern_auth(self):
        s = signin(_id="s1", client_app="Browser", auth_protocol="modern")
        assert detect_legacy_auth([s]) == []


EXTERNAL_ADDR = "attacker" + "@" + "totally-external-domain.example"
INTERNAL_ADDR = "colleague" + "@" + "contoso.onmicrosoft.com"
assert EXTERNAL_ADDR != INTERNAL_ADDR  # guard against accidental collapse of the two literals


class TestSuspiciousMailRules:
    def test_flags_external_forward(self):
        a = audit(_id="a1", operation="New-InboxRule",
                  parameters={"ForwardTo": EXTERNAL_ADDR})
        findings = detect_suspicious_mail_rules([a], tenant_domains=["contoso.onmicrosoft.com"])
        assert len(findings) == 1
        assert findings[0]["severity"] == "high"

    def test_internal_forward_is_lower_severity(self):
        a = audit(_id="a1", operation="New-InboxRule",
                  parameters={"ForwardTo": INTERNAL_ADDR})
        findings = detect_suspicious_mail_rules([a], tenant_domains=["contoso.onmicrosoft.com"])
        assert findings[0]["severity"] == "medium"

    def test_flags_delete_message(self):
        a = audit(_id="a1", operation="Set-InboxRule", parameters={"DeleteMessage": True})
        findings = detect_suspicious_mail_rules([a])
        assert any(f["rule"] == "suspicious_mail_rule_delete" for f in findings)

    def test_ignores_unrelated_operations(self):
        a = audit(_id="a1", operation="Set-Mailbox", parameters={"ForwardTo": "x"})
        assert detect_suspicious_mail_rules([a]) == []


class TestRiskyAppConsent:
    def test_flags_non_admin_risky_scope(self):
        a = audit(_id="a1", operation="Consent to application",
                  parameters={"AppDisplayName": "Evil App", "scopes": ["Mail.Read"], "IsAdminConsent": False})
        findings = detect_risky_app_consent([a])
        assert len(findings) == 1

    def test_ignores_admin_consent(self):
        a = audit(_id="a1", operation="Consent to application",
                  parameters={"scopes": ["Mail.Read"], "IsAdminConsent": True})
        assert detect_risky_app_consent([a]) == []

    def test_ignores_low_risk_scopes(self):
        a = audit(_id="a1", operation="Consent to application",
                  parameters={"scopes": ["User.Read"], "IsAdminConsent": False})
        assert detect_risky_app_consent([a]) == []


class TestSummarizeTriage:
    def test_no_findings_gives_negative_answers(self):
        summary = summarize_triage([])
        assert summary["likely_compromised_accounts"] == []
        answers = {a["question"]: a["answer"] for a in summary["answers"]}
        assert "No account" in answers["Which accounts are likely compromised?"]

    def test_full_scenario_recommends_legal_and_investigation(self):
        s1 = signin(_id="s1", user_principal_name="[email protected]",
                    location_country="US")
        s2 = signin(_id="s2", user_principal_name="[email protected]",
                    location_country="NG", risk_level="high",
                    timestamp=(NOW + timedelta(minutes=20)).isoformat())
        a1 = audit(_id="a1", operation="New-InboxRule", user_principal_name="[email protected]",
                  parameters={"ForwardTo": "[email protected]"})

        findings = run_all_rules([s1, s2], [a1], tenant_domains=["contoso.onmicrosoft.com"])
        summary = summarize_triage(findings)

        assert "[email protected]" in summary["likely_compromised_accounts"]
        answers = {a["question"]: a for a in summary["answers"]}
        assert "Yes" in answers["Is legal support recommended?"]["answer"]
        assert "Recommended" in answers["Is a full forensic investigation recommended?"]["answer"]
