# Solitude Triage Service

A Python/FastAPI service that ingests M365-style logs (Entra ID sign-ins and
Unified Audit Log records) into Elasticsearch and runs a rule-based triage
engine over them. This implements the **Phase 2 Triage Assessment Module**
described in the Solitude Reloaded Technical Design Document: a fast,
limited-scope assessment that answers a fixed set of decision-support
questions, distinct from a full forensic investigation.

## What it detects

| Rule | What it flags |
|---|---|
| `impossible_travel` | Same user, successful sign-ins from two different countries in a time window too short for real travel |
| `risky_signin_flag` | Sign-ins Entra ID itself already scored medium/high risk |
| `legacy_auth` | Successful sign-in via legacy/basic-auth clients (POP, IMAP, SMTP AUTH, etc.) — not covered by modern-auth Conditional Access |
| `suspicious_mail_rule` | Inbox/transport rules that forward or redirect mail, especially to an external domain |
| `suspicious_mail_rule_delete` | Inbox/transport rules that silently delete matching messages (used to hide fraud reply traffic) |
| `risky_app_consent` | Non-admin consent grants to applications requesting high-impact scopes (`Mail.Read`, `Mail.ReadWrite`, etc.) |

Findings feed into a triage summary that answers:
1. Which accounts are likely compromised?
2. What data may be at risk?
3. Is legal support recommended?
4. Is a full forensic investigation recommended?

Every answer carries the finding IDs / evidence it's based on.

## Architecture

```
Log file (.jsonl) or JSON POST
        │
        ▼
 FastAPI ingestion endpoint  ──indexes──▶  Elasticsearch
        │                                  (per-case indices:
        │                                   m365-signin-logs-{case_id},
        │                                   m365-audit-logs-{case_id})
        ▼
 Triage endpoint fetches case's logs ──▶ rule engine (app/rules.py, pure
                                          functions, no ES dependency) ──▶
                                          triage report (JSON)
```

`app/rules.py` has no Elasticsearch dependency by design — it's pure
functions over plain dicts, so the detection logic is fully unit-testable
without a running cluster (see `tests/test_rules.py`).

## Running locally

Requires Docker (for Elasticsearch) — or point `APP_ELASTICSEARCH_URL` at
an existing cluster.

```bash
docker compose up --build
```

This starts Elasticsearch (`localhost:9200`), Kibana (`localhost:5601`,
optional, for browsing raw indices), and the API (`localhost:8000`).
API docs: `http://localhost:8000/docs`.

### Generate and ingest sample data

```bash
python scripts/generate_sample_logs.py --case-id SR-2026-0501 --out-dir sample_data

curl -X POST 'http://localhost:8000/ingest/SR-2026-0501/file?log_type=signin' \
  -F 'file=@sample_data/SR-2026-0501-signin.jsonl'

curl -X POST 'http://localhost:8000/ingest/SR-2026-0501/file?log_type=audit' \
  -F 'file=@sample_data/SR-2026-0501-audit.jsonl'

curl 'http://localhost:8000/triage/SR-2026-0501?tenant_domain=contoso.onmicrosoft.com' | python -m json.tool
```

The generated sample data plants one compromised account (`d.farrow` by
default — override with `--compromised-user`) amid normal background
activity for four other users, so the triage output should flag exactly
that one account.

### One-shot demo: logs + Kibana dashboards

```bash
./demo/run_demo.sh
```

This brings up the full stack, ingests three bundled demo cases
(`demo/sample_data/`, one planted compromised account each), and
provisions a Kibana dashboard via `kibana/provision_dashboards.py`. When it
finishes, open:

```
http://localhost:5601/app/dashboards#/view/solitude-m365-triage-overview
```

The dashboard has 7 panels:

- **Sign-ins over time by risk level** — date histogram, split by Entra risk level
- **Sign-ins by country** — spot geographic outliers
- **Client app usage** — legacy/basic-auth clients vs modern auth
- **Top users by sign-in volume**
- **Audit log operations breakdown** — inbox rules, consent grants, etc.
- **Risky / legacy-auth sign-ins** — saved search, pre-filtered
- **Mail rule & app consent audit events** — saved search, pre-filtered

Filter any panel to a single incident by typing `case_id: "SR-2026-0501"`
(or whichever case) into the dashboard's search bar.

To provision dashboards against a stack you've already loaded data into
(skipping the ingestion step), run just the provisioning script:

```bash
pip install requests
python kibana/provision_dashboards.py --kibana-url http://localhost:5601
```

It's idempotent — every object has a fixed id and is created with
`overwrite=true`, so re-running it after re-ingesting data just refreshes
the same dashboard rather than duplicating it.

### Run tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

## API summary

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ingest/{case_id}/signin` | Bulk-index sign-in log records (JSON body) |
| `POST` | `/ingest/{case_id}/audit` | Bulk-index audit log records (JSON body) |
| `POST` | `/ingest/{case_id}/file?log_type=signin\|audit` | Ingest a `.jsonl` file |
| `GET` | `/logs/{case_id}/signin` | List raw ingested sign-in logs |
| `GET` | `/logs/{case_id}/audit` | List raw ingested audit logs |
| `GET` | `/triage/{case_id}?tenant_domain=...` | Full triage report: findings + answers |
| `GET` | `/triage/{case_id}/findings` | Just the finding list |
| `GET` | `/healthz` | Service + Elasticsearch cluster health |

## Configuration

Environment variables (prefix `APP_`), see `.env.example`:

- `APP_ELASTICSEARCH_URL` (default `http://localhost:9200`)
- `APP_ELASTICSEARCH_USERNAME` / `APP_ELASTICSEARCH_PASSWORD` (optional)

Rule thresholds (impossible-travel speed, legacy-auth client list, risky
consent scopes) are configurable in `app/config.py`.

## Repo layout

```
app/                  FastAPI service (routes, ES client, pure rule engine)
scripts/              generate_sample_logs.py — synthetic M365 log generator
tests/                unit tests for the rule engine (no ES required)
kibana/               provision_dashboards.py — scripted Kibana dashboard setup
demo/
  sample_data/        bundled demo log fixtures (3 cases, committed to the repo)
  run_demo.sh         one-shot: docker compose up, ingest demo data, provision dashboards
ai-analysis-mcp/      MCP server: AI-assisted analysis over findings, backed by a
                      local Ollama model (evidence-grounded, with a rejection-rate
                      circuit breaker) — see ai-analysis-mcp/README.md
```

## Known limitations

- `impossible_travel` uses country-centroid distance as a rough proxy —
  it's a heuristic, not a precise geolocation calculation, and will miss
  or misjudge edge cases (e.g. large countries, VPN exit nodes).
- Each case's logs live in per-case Elasticsearch indices; there's no
  cross-case correlation.
- No authentication on the API itself — put it behind your own
  auth/gateway before exposing it beyond local development.
- Not connected to a real Microsoft Graph tenant — logs must be ingested
  via the API (e.g. from an export, or the sample generator).
