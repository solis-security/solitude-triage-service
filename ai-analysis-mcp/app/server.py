"""Solitude AI Analysis MCP server.

Exposes the TDD's AI-Assisted Analysis Engine (Section 4.4) as MCP tools,
backed by a local Ollama model instead of a hosted API. Every analysis
tool enforces evidence grounding: a conclusion that cites no evidence, or
cites an evidence id it was never given, is rejected before it's returned
— matching the TDD's 'validation step before AI findings reach the
analyst review queue'.

Run with:
    python -m app.server
or configure it as an MCP server in Claude Desktop / Claude Code (see
README.md for the config snippet).
"""

from mcp.server.fastmcp import FastMCP

from app import analysis
from app.schemas import EvidenceItem, FindingInput

mcp = FastMCP("solitude-ai-analysis")


@mcp.tool()
def analyze_finding(finding_id: str, rule: str, severity: str, area: str, text: str, evidence: list[dict]) -> dict:
    """Produce an evidence-grounded AI analysis of a single investigation finding.

    Args:
        finding_id: The finding's id (e.g. "F-1006").
        rule: The rule that generated this finding (e.g. "impossible_travel").
        severity: One of "low", "medium", "high".
        area: The investigation area (e.g. "Authentication and sign-ins").
        text: The rule-generated description of the finding.
        evidence: List of evidence records, each with "id", "source", and "summary".
            Only these evidence ids may appear in the response's evidence_refs.
    """
    validated = FindingInput(
        id=finding_id, rule=rule, severity=severity, area=area, text=text,
        evidence=[EvidenceItem(**e) for e in evidence],
    )
    result = analysis.analyze_finding(validated.model_dump())
    return {"finding_id": finding_id, **result.model_dump()}


@mcp.tool()
def summarize_case(findings: list[dict]) -> dict:
    """Produce an evidence-grounded executive summary across all findings in a case.

    Args:
        findings: List of findings, each shaped like the input to analyze_finding
            (id, rule, severity, area, text, evidence: [{id, source, summary}]).
    """
    validated = [FindingInput(**f).model_dump() for f in findings]
    result = analysis.summarize_case(validated)
    return result.model_dump()


@mcp.tool()
def analyze_email_content(evidence_id: str, subject: str, body: str = None) -> dict:
    """Assess whether an email's content indicates sensitive data exposure.

    Falls back to subject-line-only analysis (explicitly flagged as such)
    when no message body is available or accessible.

    Args:
        evidence_id: The evidence id this message corresponds to.
        subject: The message subject line.
        body: The message body, if accessible. Omit or pass null if not available.
    """
    result = analysis.analyze_email_content(evidence_id, subject, body)
    return result.model_dump()


@mcp.tool()
def get_ai_engine_health() -> dict:
    """Report AI engine health: whether Ollama is reachable, which models
    are available locally, and whether the rejection-rate circuit breaker
    has tripped (in which case AI findings should not be auto-included in
    reports until it clears)."""
    return analysis.get_engine_health().model_dump()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
