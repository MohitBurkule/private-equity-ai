#!/usr/bin/env bash
# Quick Rust vs FastAPI latency check. Needs both servers up (see docs), a bench key in $KEY_FILE, and oha on PATH.
# Same box runs load + servers, so numbers are relative, not absolute.
set -euo pipefail
K=$(cat "${KEY_FILE:?set KEY_FILE to a file holding an API key}")
run() {
  o=$(oha -z "${DUR:-10s}" -c "${CONC:-50}" --no-tui -H "Authorization: Bearer $K" "$1" 2>&1)
  echo "$2 $(echo "$o" | awk '/Requests\/sec/{printf "rps=%.0f ",$2} /Success rate/{printf "ok=%s ",$3} /50.00% in/{printf "p50=%s ",$3} /95.00% in/{printf "p95=%s ",$3} /99.00% in/{printf "p99=%s",$3}') ms"
}
run "${FASTAPI_URL:-http://127.0.0.1:8000}/health" fastapi_health
run "${RUST_URL:-http://127.0.0.1:8001}/health" rust_health
run "${FASTAPI_URL:-http://127.0.0.1:8000}/facts" fastapi_facts_auth_db
run "${RUST_URL:-http://127.0.0.1:8001}/me" rust_me_auth_db
