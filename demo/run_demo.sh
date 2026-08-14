#!/usr/bin/env bash
# Brings up docker-compose, waits for the API + Kibana to be healthy, ingests
# the bundled demo log set (demo/sample_data), and provisions Kibana
# dashboards. Run from the repo root:
#
#   ./demo/run_demo.sh
#
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"
SAMPLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/sample_data"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

wait_for() {
  local url="$1" label="$2" tries=0
  echo "Waiting for $label at $url ..."
  until curl -sf "$url" > /dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -gt 60 ]; then
      echo "Timed out waiting for $label" >&2
      exit 1
    fi
    sleep 3
  done
  echo "$label is up."
}

echo "== Starting docker compose stack =="
(cd "$REPO_ROOT" && docker compose up -d --build)

wait_for "$API_URL/healthz" "triage API"
wait_for "$KIBANA_URL/api/status" "Kibana"

echo "== Ingesting demo log sets =="
for signin_file in "$SAMPLE_DIR"/*-signin.jsonl; do
  case_id="$(basename "$signin_file" -signin.jsonl)"
  audit_file="$SAMPLE_DIR/${case_id}-audit.jsonl"
  echo "  case $case_id"
  curl -sf -X POST "$API_URL/ingest/$case_id/file?log_type=signin" -F "file=@$signin_file" > /dev/null
  curl -sf -X POST "$API_URL/ingest/$case_id/file?log_type=audit" -F "file=@$audit_file" > /dev/null
done

echo "== Provisioning Kibana dashboards =="
python3 -m pip install --quiet requests
python3 "$REPO_ROOT/kibana/provision_dashboards.py" --kibana-url "$KIBANA_URL"

echo
echo "Done."
echo "  API docs:   $API_URL/docs"
echo "  Dashboard:  $KIBANA_URL/app/dashboards#/view/solitude-m365-triage-overview"
echo "  Try a triage report, e.g.:"
for signin_file in "$SAMPLE_DIR"/*-signin.jsonl; do
  case_id="$(basename "$signin_file" -signin.jsonl)"
  echo "    curl '$API_URL/triage/$case_id?tenant_domain=contoso.onmicrosoft.com' | python3 -m json.tool"
done
