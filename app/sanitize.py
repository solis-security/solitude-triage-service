"""Neutralise tenant-controlled text before it reaches a prompt or a report.

Finding text and evidence summaries both carry values chosen by whoever
created the underlying object — an attacker who registers an OAuth
application names it, and who creates a mail rule chooses its recipients.
Both strings are interpolated into the prompt sent to the analysis model,
and both are rendered to human analysts, so neither can carry raw
attacker-supplied content.

This is defence in depth. The analysis engine still validates every
conclusion against the evidence ids it supplied, and the system prompts
state that evidence is data rather than instructions.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Long enough to identify an application or recipient, short enough that it
# cannot carry a useful instruction block.
MAX_ECHO = 80

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


def safe_text(value: Any, limit: int = MAX_ECHO) -> str:
    """Collapse newlines, strip control and format characters, cap length.

    Newlines are what let injected text pose as a new instruction block, so
    they go first. Unicode format characters (category Cf) include the
    bidirectional overrides that make a string read one way to a human
    reviewer and another to the model.
    """
    text = unicodedata.normalize("NFKC", str(value))
    text = _CONTROL.sub(" ", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    text = _WHITESPACE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


_TRUE = {"true", "t", "yes", "y", "1", "on"}
_FALSE = {"false", "f", "no", "n", "0", "off", "", "none", "null"}


def as_bool(value: Any) -> bool:
    """Coerce an audit-log flag to a boolean, string forms included.

    Unified Audit Log adapters routinely serialise parameter values as
    strings, and plain truthiness reads "False" as true — which turned
    `DeleteMessage: "False"` into "the rule deletes matching messages" and
    `IsAdminConsent: "False"` into "Admin consent: yes". Both are stated to
    the model as fact, and the second contradicted the rule engine, which
    read the same value the other way and emitted no finding.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return bool(text)
