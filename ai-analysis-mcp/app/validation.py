"""Pure functions: no Ollama or MCP dependency, so they're testable with
plain data. This is where the TDD's 'evidence-reference validation before
any AI finding reaches the review queue' actually gets enforced."""

from __future__ import annotations


def validate_grounding(evidence_refs: list[str], provided_evidence_ids: list[str], insufficient_evidence: bool) -> str:
    """Returns one of: 'grounded', 'rejected_no_evidence', 'rejected_ungrounded'.

    - The model can legitimately say "insufficient_evidence" with no refs —
      that's a grounded, honest response, not a rejection.
    - If it claims a conclusion (insufficient_evidence=False) but cites no
      evidence, or cites an evidence id we never gave it, reject it.
    """
    if insufficient_evidence:
        return "grounded"
    if not evidence_refs:
        return "rejected_no_evidence"
    if not set(evidence_refs).issubset(set(provided_evidence_ids)):
        return "rejected_ungrounded"
    return "grounded"


def compute_engine_health(recent_validations: list[str], window: int, threshold: float) -> dict:
    """recent_validations: most-recent-last list of validation statuses
    (e.g. from the audit log), already trimmed by the caller to the last
    `window` entries at most."""
    recent = recent_validations[-window:]
    rejected = sum(1 for v in recent if v.startswith("rejected") or v == "engine_error")
    rate = (rejected / len(recent)) if recent else 0.0
    return {
        "window_size": window,
        "calls_in_window": len(recent),
        "rejected_in_window": rejected,
        "rejection_rate": rate,
        "circuit_breaker_tripped": len(recent) >= 5 and rate > threshold,
    }
