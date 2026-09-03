"""Regression tests for the case_id index-wildcard leak.

An unvalidated case_id reached Elasticsearch inside an index name. Because
index expressions accept wildcards, `GET /triage/*` resolved to
`m365-signin-logs-*` and returned a single triage report spanning every case
in the cluster — reproduced against a live Elasticsearch across three cases
belonging to different customers.
"""

import pytest
from fastapi.testclient import TestClient

from app.case_id import require_case_id
from app.es_client import audit_index, signin_index
from app.main import app

client = TestClient(app)

# Each of these is a valid Elasticsearch index expression, which is exactly
# why none of them may be a valid case_id.
DANGEROUS = [
    "*",                       # every case index in the cluster
    "SR-2026-0501,acme-001",   # explicit multi-index list
    "sr-*",                    # prefix wildcard
    "",                        # empty — collapses to the bare index prefix
    "../etc",
    "a" * 65,                  # over the length ceiling
]

VALID = ["SR-2026-0501", "acme-001", "case_1", "a", "A" * 64]


@pytest.mark.parametrize("case_id", DANGEROUS)
def test_require_case_id_rejects_index_expressions(case_id):
    with pytest.raises(ValueError):
        require_case_id(case_id)


@pytest.mark.parametrize("case_id", VALID)
def test_require_case_id_accepts_ordinary_identifiers(case_id):
    assert require_case_id(case_id) == case_id


@pytest.mark.parametrize("case_id", DANGEROUS)
def test_index_names_cannot_be_built_from_dangerous_input(case_id):
    """Guard the index builders directly, not just the HTTP layer — a script or
    a future caller must get the same protection as a request."""
    with pytest.raises(ValueError):
        signin_index(case_id)
    with pytest.raises(ValueError):
        audit_index(case_id)


def test_reserved_looking_names_are_neutralised_by_the_prefix():
    """`_all` is Elasticsearch's all-indices alias, and it passes the pattern
    because underscores are legitimate in a case id. It is not a bypass: the
    index prefix is mandatory, so it can only ever name the literal index
    `m365-signin-logs-_all`. Only metacharacters that keep their meaning when
    prefixed — wildcards and commas — are dangerous, and those are rejected."""
    assert signin_index("_all") == "m365-signin-logs-_all"


def test_index_name_is_the_case_and_nothing_else():
    assert signin_index("SR-2026-0501").endswith("-sr-2026-0501")
    assert "*" not in signin_index("SR-2026-0501")


# "" and "../etc" do not survive URL routing as a path segment, so they are
# exercised at the function level above rather than over HTTP.
ROUTABLE = ["*", "SR-2026-0501,acme-001", "sr-*", "a" * 65]


@pytest.mark.parametrize("case_id", ROUTABLE)
@pytest.mark.parametrize(
    "path",
    [
        "/triage/{}",
        "/triage/{}/findings",
        # Added on main after this fix was written: it feeds the AI analysis
        # engine, so a widened query here would put other customers' records
        # into a model prompt.
        "/triage/{}/analysis-input",
        "/logs/{}/signin",
        "/logs/{}/audit",
    ],
)
def test_routes_reject_dangerous_case_ids(case_id, path):
    """422 before any storage call. These assertions hold with no Elasticsearch
    running: rejection happens at the edge, which is the point."""
    assert client.get(path.format(case_id)).status_code == 422


@pytest.mark.parametrize("case_id", ROUTABLE)
def test_ingest_routes_reject_dangerous_case_ids(case_id):
    assert client.post(f"/ingest/{case_id}/signin", json=[]).status_code == 422
    assert client.post(f"/ingest/{case_id}/audit", json=[]).status_code == 422
