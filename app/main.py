from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.es_client import cluster_health
from app.routes_ingest import router as ingest_router
from app.routes_logs import router as logs_router
from app.routes_triage import router as triage_router

app = FastAPI(
    title="Solitude Triage Service",
    description=(
        "Ingests M365-style sign-in and audit logs into Elasticsearch and runs "
        "a rule-based triage engine — the Phase 2 Triage Assessment Module from "
        "the Solitude Reloaded TDD."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(triage_router)
app.include_router(logs_router)


@app.get("/healthz")
def healthz():
    try:
        health = cluster_health()
        return {"status": "ok", "elasticsearch": health.get("status")}
    except Exception as e:  # noqa: BLE001
        return {"status": "degraded", "error": str(e)}
