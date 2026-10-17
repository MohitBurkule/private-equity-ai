#!/usr/bin/env bash
# Matched Rust vs FastAPI latency over native and relayed routes, same DB and tenant key.
# Start both stacks with RATE_LIMIT_PER_MIN set high (or 0 on FastAPI): the default 600/min per tenant returns 429s
# under load and skews results. Load generator and servers share one box: compare the stacks, not absolute numbers.
set -euo pipefail
K=$(cat "${KEY_FILE:?set KEY_FILE to a file holding an API key}")
ENTITY="${ENTITY:-Bench}"
DOC="${DOC:?set DOC to a document id}"
PAGE="${PAGE:-1}"
FA="${FASTAPI_URL:-http://127.0.0.1:8000}"
RS="${RUST_URL:-http://127.0.0.1:8001}"
run() {
  o=$(oha -z "${DUR:-10s}" -c "${CONC:-50}" --no-tui -H "Authorization: Bearer $K" "$1" 2>&1)
  echo "$2 $(echo "$o" | awk '/Requests\/sec/{printf "rps=%.0f ",$2} /Success rate/{printf "ok=%s ",$3} /50.00% in/{printf "p50=%s%s ",$3,$4} /99.00% in/{printf "p99=%s%s",$3,$4}') $(echo "$o" | grep -o '\[[0-9]*\] [0-9]* responses' | tr '\n' ' ')"
}
for path in "health" "facts?entity=$ENTITY" "documents" "documents/$DOC/pages/$PAGE" "memo/templates" "memo/versions?entity=$ENTITY"; do
  run "$FA/$path" "fastapi /$path"
  run "$RS/$path" "rust    /$path"
done
