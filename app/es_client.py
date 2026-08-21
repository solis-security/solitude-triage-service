from __future__ import annotations

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk, scan

from app.config import settings

# Ceiling on how many documents a single triage will pull per log type.
# High enough that real cases are analysed in full, low enough to bound
# memory; exceeding it is reported rather than passed over in silence.
MAX_TRIAGE_DOCS = 50_000

SIGNIN_MAPPING = {
    "properties": {
        "case_id": {"type": "keyword"},
        "timestamp": {"type": "date"},
        "user_principal_name": {"type": "keyword"},
        "ip_address": {"type": "ip"},
        "location_country": {"type": "keyword"},
        "device": {"type": "keyword"},
        "client_app": {"type": "keyword"},
        "auth_protocol": {"type": "keyword"},
        "status": {"type": "keyword"},
        "risk_level": {"type": "keyword"},
        "conditional_access_status": {"type": "keyword"},
    }
}

AUDIT_MAPPING = {
    "properties": {
        "case_id": {"type": "keyword"},
        "timestamp": {"type": "date"},
        "operation": {"type": "keyword"},
        "user_principal_name": {"type": "keyword"},
        "workload": {"type": "keyword"},
        "parameters": {"type": "object", "enabled": True},
        "result_status": {"type": "keyword"},
    }
}

_client: Elasticsearch | None = None


def get_client() -> Elasticsearch:
    global _client
    if _client is None:
        kwargs: dict = {}
        if settings.elasticsearch_username and settings.elasticsearch_password:
            kwargs["basic_auth"] = (settings.elasticsearch_username, settings.elasticsearch_password)
        _client = Elasticsearch(settings.elasticsearch_url, **kwargs)
    return _client


def signin_index(case_id: str) -> str:
    return f"{settings.signin_index_prefix}-{case_id}".lower()


def audit_index(case_id: str) -> str:
    return f"{settings.audit_index_prefix}-{case_id}".lower()


def ensure_index(index: str, mapping: dict) -> None:
    client = get_client()
    if not client.indices.exists(index=index):
        client.indices.create(index=index, mappings=mapping)


def bulk_index(index: str, docs: list[dict]) -> tuple[int, list[str]]:
    """Bulk index documents. Returns (success_count, error_messages)."""
    actions = ({"_index": index, "_id": doc["id"], "_source": doc} for doc in docs)
    success, errors = bulk(get_client(), actions, raise_on_error=False, stats_only=False)
    error_messages = [str(e) for e in errors] if errors else []
    return success, error_messages


def search_all(index: str, query: dict | None = None, size: int = 1000) -> list[dict]:
    """Fetch up to `size` documents from an index, returning _source with the
    document id attached as `_id`."""
    docs, _ = search_all_paged(index, query=query, max_docs=size)
    return docs


def scan_all(index: str, query: dict | None = None, max_docs: int = MAX_TRIAGE_DOCS) -> tuple[list[dict], bool]:
    """Fetch every document in an index, up to a hard ceiling.

    Returns (docs, truncated). A single capped `search` silently analysed
    only the first page, so a large case was triaged on a partial slice with
    nothing said about it — the caller needs to know when that happens.
    """
    return search_all_paged(index, query=query, max_docs=max_docs, paged=True)


def search_all_paged(
    index: str,
    query: dict | None = None,
    max_docs: int = 1000,
    paged: bool = False,
) -> tuple[list[dict], bool]:
    client = get_client()
    if not client.indices.exists(index=index):
        return [], False
    body = query or {"match_all": {}}

    if not paged:
        resp = client.search(index=index, query=body, size=max_docs)
        hits = resp["hits"]["hits"]
        total = resp["hits"]["total"]["value"] if isinstance(resp["hits"]["total"], dict) else len(hits)
        results = []
        for hit in hits:
            doc = hit["_source"]
            doc["_id"] = hit["_id"]
            results.append(doc)
        return results, total > len(results)

    results: list[dict] = []
    truncated = False
    # scan() takes the full request body, unlike client.search(query=...)
    # which takes the query clause on its own.
    #
    # Ordered by timestamp deliberately. With preserve_order=False the scroll
    # returns an arbitrary index-order slice, so "the first 50,000 records"
    # was neither chronological nor stable — two triages of the same
    # oversized case could analyse different subsets as segments merged, and
    # findings would appear and disappear between runs. For a forensic
    # report, a reproducible chronological prefix is worth the slower scroll.
    for hit in scan(
        client,
        index=index,
        query={"query": body, "sort": [{"timestamp": "asc"}]},
        preserve_order=True,
    ):
        if len(results) >= max_docs:
            truncated = True
            break
        doc = hit["_source"]
        doc["_id"] = hit["_id"]
        results.append(doc)
    return results, truncated


def cluster_health() -> dict:
    return dict(get_client().cluster.health())
