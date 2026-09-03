"""Case identifier validation.

`case_id` arrives from the URL path and ends up inside an Elasticsearch index
name. Elasticsearch index expressions accept wildcards and comma-separated
lists, so an unvalidated identifier is not merely malformed input — it is a
query across other customers' cases. A `case_id` of `*` resolved to
`m365-signin-logs-*`, and a single unauthenticated GET returned one triage
report spanning every case in the cluster.

The constraint therefore lives in two places on purpose. The FastAPI path type
rejects bad input at the edge with a 422, and `require_case_id` guards index
construction itself, so no code path — route, script or future caller — can
build an index name that widens a query.
"""

from __future__ import annotations

import re
from typing import Annotated

from fastapi import Path

#: Deliberately strict: an allowlist of characters that carry no meaning to an
#: Elasticsearch index expression. Anything outside it is rejected rather than
#: escaped or stripped — silently rewriting an identifier means a request for
#: one case can be answered with another.
CASE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

_CASE_ID_RE = re.compile(CASE_ID_PATTERN)

CaseId = Annotated[
    str,
    Path(
        pattern=CASE_ID_PATTERN,
        description="Case identifier: letters, digits, hyphen and underscore, up to 64 characters.",
    ),
]


def require_case_id(case_id: str) -> str:
    """Return `case_id` if it is safe to interpolate into an index name.

    Raises ValueError otherwise. Callers that reach storage without passing
    through the HTTP layer get the same guarantee.
    """
    if not isinstance(case_id, str) or not _CASE_ID_RE.match(case_id):
        raise ValueError(
            f"Invalid case_id {case_id!r}: must match {CASE_ID_PATTERN}. "
            "Wildcards and index-expression metacharacters are not permitted."
        )
    return case_id
