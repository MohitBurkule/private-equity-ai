#!/usr/bin/env bash
# Docker-free end-to-end smoke: the API as a process against Postgres and Redis on localhost,
# then the same smoke script CI runs through docker compose. Mirrors the compose-e2e job.
# Needs: a Postgres with the pe app/owner roles (see the api-postgres job), Redis on 6379,
# and ADMIN_TOKEN. Optional: a built web UI in apps/web/dist, served on WEB_PORT (default 8080).
set -euo pipefail
cd "$(dirname "$0")/.."
export ADMIN_TOKEN="${ADMIN_TOKEN:-ci-admin}"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://pe_app:a@localhost:5432/pe_ci}"
export MIGRATE_DATABASE_URL="${MIGRATE_DATABASE_URL:-postgresql+psycopg://pe_owner:o@localhost:5432/pe_ci}"
export APP_DB_ROLE="${APP_DB_ROLE:-pe_app}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export SPOOL_DIR="${SPOOL_DIR:-$(mktemp -d)}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-8080}"
pids=()
cleanup() { for p in "${pids[@]}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

(cd apps/api && exec python3 -m uvicorn app.main:app --port "$API_PORT") > "${SPOOL_DIR}/api.log" 2>&1 &
pids+=($!)
for i in $(seq 1 60); do
  curl -sf "localhost:${API_PORT}/health" >/dev/null && break
  kill -0 "${pids[0]}" 2>/dev/null || { echo "api exited, see ${SPOOL_DIR}/api.log"; tail -20 "${SPOOL_DIR}/api.log"; exit 1; }
  sleep 2
done
curl -sf "localhost:${API_PORT}/health"

if [ -f apps/web/dist/index.html ]; then
  (cd apps/web/dist && exec python3 -m http.server "$WEB_PORT") > "${SPOOL_DIR}/web.log" 2>&1 &
  pids+=($!)
  sleep 2
  curl -sf "localhost:${WEB_PORT}/" | grep -qi "<div id" && echo "web ok"
else
  echo "web: apps/web/dist not built, skipping UI check"
fi

python3 scripts/smoke.py "http://localhost:${API_PORT}" "$ADMIN_TOKEN"
echo "e2e local smoke passed"
