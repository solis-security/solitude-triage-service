from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, UploadFile

from app.es_client import AUDIT_MAPPING, SIGNIN_MAPPING, audit_index, bulk_index, ensure_index, signin_index
from app.models import AuditLogRecord, IngestResult, SignInLog

router = APIRouter(prefix="/ingest", tags=["ingestion"])


def _prepare_docs(records: list[dict], case_id: str) -> list[dict]:
    docs = []
    for r in records:
        doc = dict(r)
        doc["case_id"] = case_id
        if isinstance(doc.get("timestamp"), object) and hasattr(doc["timestamp"], "isoformat"):
            doc["timestamp"] = doc["timestamp"].isoformat()
        docs.append(doc)
    return docs


@router.post("/{case_id}/signin", response_model=IngestResult)
def ingest_signin_logs(case_id: str, records: list[SignInLog]):
    index = signin_index(case_id)
    ensure_index(index, SIGNIN_MAPPING)
    docs = _prepare_docs([r.model_dump() for r in records], case_id)
    indexed, errors = bulk_index(index, docs)
    return IngestResult(case_id=case_id, log_type="signin", received=len(records), indexed=indexed, errors=errors)


@router.post("/{case_id}/audit", response_model=IngestResult)
def ingest_audit_logs(case_id: str, records: list[AuditLogRecord]):
    index = audit_index(case_id)
    ensure_index(index, AUDIT_MAPPING)
    docs = _prepare_docs([r.model_dump() for r in records], case_id)
    indexed, errors = bulk_index(index, docs)
    return IngestResult(case_id=case_id, log_type="audit", received=len(records), indexed=indexed, errors=errors)


@router.post("/{case_id}/file", response_model=IngestResult)
async def ingest_log_file(case_id: str, log_type: str, file: UploadFile):
    """Ingest a newline-delimited JSON (.jsonl) file of sign-in or audit
    records — the format produced by scripts/generate_sample_logs.py."""
    if log_type not in ("signin", "audit"):
        raise HTTPException(400, "log_type must be 'signin' or 'audit'")

    raw = (await file.read()).decode("utf-8")
    records = []
    parse_errors: list[str] = []
    for i, line in enumerate(raw.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as e:
            parse_errors.append(f"line {i}: {e}")

    model = SignInLog if log_type == "signin" else AuditLogRecord
    validated: list[dict] = []
    for i, rec in enumerate(records):
        try:
            validated.append(model(**rec).model_dump())
        except Exception as e:  # noqa: BLE001 — surface as a per-line ingest error
            parse_errors.append(f"record {i}: {e}")

    index = signin_index(case_id) if log_type == "signin" else audit_index(case_id)
    mapping = SIGNIN_MAPPING if log_type == "signin" else AUDIT_MAPPING
    ensure_index(index, mapping)
    docs = _prepare_docs(validated, case_id)
    indexed, bulk_errors = bulk_index(index, docs) if docs else (0, [])

    return IngestResult(
        case_id=case_id,
        log_type=log_type,
        received=len(records),
        indexed=indexed,
        errors=parse_errors + bulk_errors,
    )
