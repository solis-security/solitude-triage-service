import tempfile
from pathlib import Path

import pytest

from app import analysis
from app.config import settings
from app.ollama_client import OllamaClient
from tests.mock_ollama import MockOllamaServer

SAMPLE_FINDING = {
    "id": "F-1006",
    "rule": "impossible_travel",
    "severity": "high",
    "area": "Authentication and sign-ins",
    "text": "Sign-in from US then NG within 25 minutes.",
    "evidence": [
        {"id": "EV-3381", "source": "Sign-in log", "summary": "Successful sign-in from US at 10:00 UTC."},
        {"id": "EV-3382", "source": "Sign-in log", "summary": "Successful sign-in from NG at 10:25 UTC."},
    ],
}


@pytest.fixture(autouse=True)
def isolated_audit_log(monkeypatch, tmp_path):
    """Point the audit log at a temp file per test so tests don't share state."""
    monkeypatch.setattr(settings, "audit_log_path", str(tmp_path / "audit.jsonl"))
    yield


class TestAnalyzeFinding:
    def test_happy_path_is_grounded(self):
        with MockOllamaServer() as srv:
            client = OllamaClient(host=srv.url, model="llama3.1")
            result = analysis.analyze_finding(SAMPLE_FINDING, client=client)
        assert result.validation == "grounded"
        assert set(result.evidence_refs) == {"EV-3381", "EV-3382"}
        assert result.model_digest == "sha256:abc12"
        assert result.error is None

    def test_hallucinated_evidence_is_rejected(self):
        finding = dict(SAMPLE_FINDING, text="TRIGGER_HALLUCINATE this finding")
        with MockOllamaServer() as srv:
            client = OllamaClient(host=srv.url, model="llama3.1")
            result = analysis.analyze_finding(finding, client=client)
        assert result.validation == "rejected_ungrounded"
        assert result.evidence_refs == []  # rejected output's refs are not surfaced

    def test_no_evidence_cited_is_rejected(self):
        finding = dict(SAMPLE_FINDING, text="TRIGGER_NO_EVIDENCE this finding")
        with MockOllamaServer() as srv:
            client = OllamaClient(host=srv.url, model="llama3.1")
            result = analysis.analyze_finding(finding, client=client)
        assert result.validation == "rejected_no_evidence"

    def test_model_reporting_insufficient_evidence_is_grounded(self):
        finding = dict(SAMPLE_FINDING, text="TRIGGER_INSUFFICIENT this finding")
        with MockOllamaServer() as srv:
            client = OllamaClient(host=srv.url, model="llama3.1")
            result = analysis.analyze_finding(finding, client=client)
        assert result.validation == "grounded"
        assert result.insufficient_evidence is True

    def test_malformed_model_output_is_engine_error_not_a_crash(self):
        finding = dict(SAMPLE_FINDING, text="TRIGGER_MALFORMED this finding")
        with MockOllamaServer() as srv:
            client = OllamaClient(host=srv.url, model="llama3.1")
            result = analysis.analyze_finding(finding, client=client)
        assert result.validation == "engine_error"
        assert result.error is not None

    def test_unreachable_ollama_is_engine_error_not_a_crash(self):
        client = OllamaClient(host="http://127.0.0.1:1", model="llama3.1", timeout=1)
        result = analysis.analyze_finding(SAMPLE_FINDING, client=client)
        assert result.validation == "engine_error"
        assert result.error is not None


class TestSummarizeCase:
    def test_happy_path(self):
        findings = [SAMPLE_FINDING]
        with MockOllamaServer() as srv:
            client = OllamaClient(host=srv.url, model="llama3.1")
            result = analysis.summarize_case(findings, client=client)
        assert result.validation == "grounded"
        assert result.finding_count == 1
        assert result.high_severity_count == 1


class TestAnalyzeEmailContent:
    def test_subject_fallback_when_no_body(self):
        with MockOllamaServer() as srv:
            client = OllamaClient(host=srv.url, model="llama3.1")
            result = analysis.analyze_email_content(
                "EV-9001", "TRIGGER_SUBJECT_FALLBACK Updated banking details", body=None, client=client
            )
        assert result.method == "subject_line_fallback"
        assert "invoice_or_payment_request" in result.sensitivity_flags


class TestEngineHealthIntegration:
    def test_reflects_real_rejection_history(self):
        with MockOllamaServer() as srv:
            client = OllamaClient(host=srv.url, model="llama3.1")
            # 3 grounded, 2 rejected — should show up in health after being logged
            analysis.analyze_finding(SAMPLE_FINDING, client=client)
            analysis.analyze_finding(SAMPLE_FINDING, client=client)
            analysis.analyze_finding(SAMPLE_FINDING, client=client)
            analysis.analyze_finding(dict(SAMPLE_FINDING, text="TRIGGER_NO_EVIDENCE x"), client=client)
            analysis.analyze_finding(dict(SAMPLE_FINDING, text="TRIGGER_HALLUCINATE x"), client=client)
            health = analysis.get_engine_health(client=client)
        assert health.ollama_reachable is True
        assert health.calls_in_window == 5
        assert health.rejected_in_window == 2
