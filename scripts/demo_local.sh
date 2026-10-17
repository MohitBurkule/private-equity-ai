#!/usr/bin/env bash
# One command to see the app with no Postgres, Redis or Docker: the API on SQLite, the built web UI,
# and seeded filings. Stop it with Ctrl+C. Open the UI at the printed URL and paste the printed key.
#   scripts/demo_local.sh            (or: make demo)
# Asks once for an SEC User-Agent (name and contact) for live EDGAR search; nothing personal is stored.
# Needs Python 3 with apps/api installed, and Node for the web UI. Filings are seeded when DATA_DIR
# holds the 10-K HTML files. When they are missing, make demo downloads the public 3M 10-K and XPO
# Term Loan A exhibit from EDGAR (needs SEC_USER_AGENT) and records each URL and SHA-256 in filings/manifest.json.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
DEMO_DIR="${DEMO_DIR:-$(mktemp -d)}"
mkdir -p "$DEMO_DIR"
DATA_DIR="${DATA_DIR:-$ROOT/data/demo/edgar}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
ADMIN_TOKEN="${ADMIN_TOKEN:-demo-admin-token}"
export ADMIN_TOKEN DATABASE_URL="sqlite:///$DEMO_DIR/demo.db"

# SEC rejects anonymous requests, so live EDGAR search needs a contact string. It is asked for here and never
# written to the repo. Leave it empty to skip live search; the rest of the demo does not need it.
if [ -z "${SEC_USER_AGENT:-}" ] && [ -t 0 ]; then
  read -r -p "SEC User-Agent for live EDGAR search (e.g. 'PE Platform demo you@example.com', blank to skip): " SEC_USER_AGENT || true
fi
export SEC_USER_AGENT="${SEC_USER_AGENT:-}"

pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

(cd apps/api && python3 -c "
from sqlalchemy import create_engine
from app.migrate import migrate
migrate(create_engine(\"$DATABASE_URL\"))")

(cd apps/api && exec python3 -m uvicorn app.main:app --port "$API_PORT") >"$DEMO_DIR/api.log" 2>&1 &
pids+=($!)
for _ in $(seq 1 30); do curl -sf "localhost:$API_PORT/health" >/dev/null && break; sleep 1; done
curl -sf "localhost:$API_PORT/health" >/dev/null || { echo "API did not start, see $DEMO_DIR/api.log"; exit 1; }

# Fetch the public filings when they are not local yet. Without a User-Agent the fetch is skipped, not faked.
# Cached files are checked by hash, so running this every time only downloads what is missing.
python3 scripts/fetch_demo_filings.py "$DATA_DIR" || echo "EDGAR filings not fetched; the UI starts empty."

if [ -f "$DATA_DIR/filings/3M_2019_10K.htm" ]; then
  SEED=$(python3 scripts/seed_ixbrl_facts.py "http://localhost:$API_PORT" "$ADMIN_TOKEN" "$DATA_DIR")
  KEY=$(awk '/API key/{print $3}' <<<"$SEED")
  # Term Loan A terms, a labelled-assumption LBO run, and one candidate watch over the dated cache.
  python3 scripts/demo_extras.py "http://localhost:$API_PORT" "$KEY" "$DATABASE_URL" "$DATA_DIR" "$DEMO_DIR" \
    | sed 's/^/extras: /'
  # QoE bridge, NWC peg, a DD answer and a synthetic LBO workbook, all cited to the FY2025 and FY2024 10-Ks.
  if [ -f "$DATA_DIR/filings/XPO_10-K_FY2024.htm" ]; then
    python3 scripts/seed_xpo_qoe.py "http://localhost:$API_PORT" "$KEY" "$DATA_DIR/filings" | sed 's/^/qoe: /'
  fi
  # A synthetic holding with budget, marks and a target note, for the portfolio and targets screens.
  python3 scripts/seed_portfolio_synthetic.py "http://localhost:$API_PORT" "$KEY" | sed 's/^/synthetic: /'
  # SYNTHETIC peer EVs and FY2025 revenue so the comps screen has usable peers; no real prices offline.
  python3 scripts/seed_peer_ev_synthetic.py "$DATABASE_URL" | sed 's/^/synthetic peers: /'
  echo "Dated EDGAR cache: data/demo/cache (captured 2026-10-17). Firm rule is synthetic demo text."
else
  echo "No seed data at $DATA_DIR; the UI starts empty. Add a tenant with POST /admin/tenants."
  KEY=$(curl -s -X POST "localhost:$API_PORT/admin/tenants" -H "X-Admin-Token: $ADMIN_TOKEN" \
        -H "Content-Type: application/json" -d '{"name":"demo"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['api_key'])")
fi

(cd apps/web && npm ci --silent && npx vite build >/dev/null && exec npx vite preview --port "$WEB_PORT" --strictPort) >"$DEMO_DIR/web.log" 2>&1 &
pids+=($!)
for _ in $(seq 1 60); do curl -sf "localhost:$WEB_PORT/" >/dev/null && break; sleep 1; done

echo
echo "Demo running."
echo "  UI:      http://localhost:$WEB_PORT"
echo "  API key: $KEY"
echo "  Logs:    $DEMO_DIR"
wait
