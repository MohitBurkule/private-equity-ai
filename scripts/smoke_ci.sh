#!/usr/bin/env bash
# Smoke test for every nav screen: API on SQLite with a fresh tenant, web dev server, then smoke_screens.py.
# Run by `make ci`. Needs playwright (apps/api dev extra) and a Chromium: set PW_CHROMIUM to its path when
# Playwright's own download is not available (the sandbox ships one at /opt/pw-browsers/chromium).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
WORK="$(mktemp -d)"
ADMIN_TOKEN="smoke-admin-token"
export ADMIN_TOKEN DATABASE_URL="sqlite:///$WORK/smoke.db" OCR_ENABLED=0 SEC_USER_AGENT=""

pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; rm -rf "$WORK"; }
trap cleanup EXIT

(cd apps/api && python3 -c "
from sqlalchemy import create_engine
from app.migrate import migrate
migrate(create_engine(\"$DATABASE_URL\"))")

(cd apps/api && exec python3 -m uvicorn app.main:app --port 8000) >"$WORK/api.log" 2>&1 &
pids+=($!)
for _ in $(seq 1 30); do curl -sf localhost:8000/health >/dev/null && break; sleep 1; done
curl -sf localhost:8000/health >/dev/null || { echo "API did not start"; cat "$WORK/api.log"; exit 1; }

KEY=$(curl -sf -X POST localhost:8000/admin/tenants -H "X-Admin-Token: $ADMIN_TOKEN" \
  -H "Content-Type: application/json" -d '{"name":"Smoke"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')

(cd apps/web && exec npx vite --port 5173 --strictPort) >"$WORK/web.log" 2>&1 &
pids+=($!)
for _ in $(seq 1 60); do curl -sf localhost:5173/ >/dev/null && break; sleep 1; done

python3 -I scripts/smoke_screens.py "http://localhost:5173/" "$KEY"
