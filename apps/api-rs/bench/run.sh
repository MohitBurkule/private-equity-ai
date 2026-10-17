#!/usr/bin/env bash
# Matched Rust vs FastAPI latency check on the same route and data. Both servers must be up on the same Postgres,
# with the same tenant key in $KEY_FILE and facts for ENTITY already stored. Needs oha on PATH.
# Load generator and servers share one box: numbers compare the two stacks, they are not absolute.
set -euo pipefail
K=$(cat "${KEY_FILE:?set KEY_FILE to a file holding an API key}")
ENTITY="${ENTITY:-Bench}"
run() {
  o=$(oha -z "${DUR:-10s}" -c "${CONC:-50}" --no-tui -H "Authorization: Bearer $K" "$1" 2>&1)
  echo "$2 $(echo "$o" | awk '/Requests\/sec/{printf "rps=%.0f ",$2} /Success rate/{printf "ok=%s ",$3} /50.00% in/{printf "p50=%s%s ",$3,$4} /99.00% in/{printf "p99=%s%s",$3,$4}')"
}
run "${FASTAPI_URL:-http://127.0.0.1:8000}/health" fastapi_health
run "${RUST_URL:-http://127.0.0.1:8001}/health" rust_health
run "${FASTAPI_URL:-http://127.0.0.1:8000}/facts?entity=$ENTITY" fastapi_facts_list
run "${RUST_URL:-http://127.0.0.1:8001}/facts?entity=$ENTITY" rust_facts_list
