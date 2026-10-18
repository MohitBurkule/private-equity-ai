#!/usr/bin/env bash
# Smoke test for every nav screen: API on SQLite, web dev server, then smoke_screens.py.
# Run by `make ci`. With filings in DATA_DIR/filings the demo seed runs first, so the screens render real
# cited data; without them the run uses an empty tenant and says so. No SEC files live in the repo.
# Needs playwright (apps/api dev extra) and a Chromium: set PW_CHROMIUM to its path when Playwright's own
# download is not available (the sandbox ships one at /opt/pw-browsers/chromium).
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

DATA_DIR="${DATA_DIR:-$ROOT/data/demo/edgar}"
if [ -f "$DATA_DIR/filings/3M_2019_10K.htm" ]; then
  SEED=$(python3 scripts/seed_ixbrl_facts.py "http://localhost:8000" "$ADMIN_TOKEN" "$DATA_DIR")
  KEY=$(awk '/API key/{print $3}' <<<"$SEED")
  python3 scripts/demo_extras.py "http://localhost:8000" "$KEY" "$DATABASE_URL" "$DATA_DIR" "$WORK" >/dev/null
  if [ -f "$DATA_DIR/filings/XPO_10-K_FY2024.htm" ]; then
    python3 scripts/seed_xpo_qoe.py "http://localhost:8000" "$KEY" "$DATA_DIR/filings" >/dev/null
  fi
  python3 scripts/seed_portfolio_synthetic.py "http://localhost:8000" "$KEY" >/dev/null
  python3 scripts/seed_peer_ev_synthetic.py "$DATABASE_URL" >/dev/null
  echo "smoke: demo data from $DATA_DIR"
else
  echo "smoke: demo smoke skipped, no filings at $DATA_DIR/filings; running on an empty tenant"
  KEY=$(curl -sf -X POST localhost:8000/admin/tenants -H "X-Admin-Token: $ADMIN_TOKEN" \
    -H "Content-Type: application/json" -d '{"name":"Smoke"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')
fi

(cd apps/web && exec npx vite --port 5173 --strictPort) >"$WORK/web.log" 2>&1 &
pids+=($!)
for _ in $(seq 1 60); do curl -sf localhost:5173/ >/dev/null && break; sleep 1; done

python3 -I scripts/smoke_screens.py "http://localhost:5173/" "$KEY"
