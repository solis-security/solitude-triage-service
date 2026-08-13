from __future__ import annotations

from fastapi import APIRouter

from app.es_client import audit_index, search_all, signin_index

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("/{case_id}/signin")
def list_signin_logs(case_id: str, size: int = 100):
    return search_all(signin_index(case_id), size=size)


@router.get("/{case_id}/audit")
def list_audit_logs(case_id: str, size: int = 100):
    return search_all(audit_index(case_id), size=size)
