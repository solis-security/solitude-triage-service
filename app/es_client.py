from __future__ import annotations

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from app.config import settings

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
    client = get_client()
    if not client.indices.exists(index=index):
        return []
    body = query or {"match_all": {}}
    resp = client.search(index=index, query=body, size=size)
    results = []
    for hit in resp["hits"]["hits"]:
        doc = hit["_source"]
        doc["_id"] = hit["_id"]
        results.append(doc)
    return results


def cluster_health() -> dict:
    return dict(get_client().cluster.health())
