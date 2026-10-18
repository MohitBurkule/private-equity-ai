#!/usr/bin/env bash
# Parity suite: FastAPI and the Rust API on a throwaway embedded Postgres, the same requests replayed against both,
# with status, body and audit rows diffed (apps/api-rs/parity/run.py). Optional; make ci does not run it.
# Needs a non-root user for Postgres (PG_RUN_AS), cargo, and the apps/api dev extras (uvicorn, psycopg).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PARITY_PG_PORT:-55434}"
FA_PORT="${PARITY_FASTAPI_PORT:-8100}"
RS_PORT="${PARITY_RUST_PORT:-8101}"
DIR="$(mktemp -d /tmp/pe-parity-XXXXXX)"
RUN_AS="${PG_RUN_AS:-}"

if ! python3 -c "import embedded_postgres" 2>/dev/null; then
  python3 -m pip install --quiet embedded-postgres
fi
BIN="$(python3 -c 'import os, embedded_postgres; print(os.path.join(os.path.dirname(embedded_postgres.__file__), "pginstall", "bin"))')"

pg() { if [ -n "$RUN_AS" ] && [ "$(id -u)" = 0 ]; then runuser -u "$RUN_AS" -- "$@"; else "$@"; fi; }

if [ "$(id -u)" = 0 ] && [ -z "$RUN_AS" ]; then
  echo "Postgres will not start as root: set PG_RUN_AS to a non-root user." >&2
  exit 1
fi
if [ -n "$RUN_AS" ]; then chown -R "$RUN_AS" "$DIR"; fi

stop_all() {
  for pidf in "$DIR"/*.pid; do [ -f "$pidf" ] && kill "$(cat "$pidf")" 2>/dev/null || true; done
  pg "$BIN/pg_ctl" -D "$DIR/data" -m fast stop >/dev/null 2>&1 || true
  rm -rf "$DIR"
}
trap stop_all EXIT

# A local Graph stand-in with a per-run certificate: both stacks read their directory calls from it.
GRAPH_PORT="${PARITY_GRAPH_PORT:-8443}"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$DIR/graph.key" -out "$DIR/graph.pem" -days 2 \
  -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" -addext "basicConstraints=critical,CA:FALSE" >/dev/null 2>&1
python3 "$ROOT/apps/api-rs/parity/fake_graph.py" "$GRAPH_PORT" "$DIR/graph.pem" "$DIR/graph.key" \
  "https://127.0.0.1:$GRAPH_PORT/v1.0" >"$DIR/graph.log" 2>&1 &
echo $! >"$DIR/graph.pid"
for _ in $(seq 1 50); do curl -sk -o /dev/null "https://127.0.0.1:$GRAPH_PORT/" && break; sleep 0.1; done

wait_http() { # url, seconds
  for _ in $(seq 1 $(( $2 * 10 ))); do curl -sf -o /dev/null "$1" && return 0; sleep 0.1; done
  echo "timed out waiting for $1" >&2; return 1
}

pg "$BIN/initdb" -D "$DIR/data" -U postgres --auth=trust --encoding=UTF8 --locale=C >"$DIR/initdb.log" 2>&1
pg "$BIN/pg_ctl" -D "$DIR/data" -l "$DIR/pg.log" -w -o "-p $PORT -k $DIR" start >/dev/null
pg "$BIN/psql" -h localhost -p "$PORT" -U postgres -v ON_ERROR_STOP=1 -q <<SQL
CREATE ROLE app_user LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE pe_parity OWNER postgres ENCODING UTF8 TEMPLATE template0;
SQL

# FastAPI runs the migrations as the owner, then serves as the non-bypass app role (as production does).
(
  cd "$ROOT/apps/api"
  mkdir -p "$DIR/spool"
  DATABASE_URL="postgresql+psycopg://app_user@localhost:$PORT/pe_parity" \
  MIGRATE_DATABASE_URL="postgresql+psycopg://postgres@localhost:$PORT/pe_parity" \
  APP_DB_ROLE=app_user ADMIN_TOKEN=test-admin RATE_LIMIT_PER_MIN=0 SPOOL_DIR="$DIR/spool" \
  PE_TEST_MODE=1 GRAPH_BASE_URL="https://127.0.0.1:$GRAPH_PORT/v1.0" SSL_CERT_FILE="$DIR/graph.pem" \
    nohup python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$FA_PORT" >"$DIR/fastapi.log" 2>&1 &
  echo $! >"$DIR/fastapi.pid"
)
wait_http "http://127.0.0.1:$FA_PORT/health" 120

(
  cd "$ROOT/apps/api-rs"
  cargo build --release --quiet
  DATABASE_URL="postgres://app_user@localhost:$PORT/pe_parity" ADMIN_TOKEN=test-admin \
  PE_TEST_MODE=1 GRAPH_BASE_URL="https://127.0.0.1:$GRAPH_PORT/v1.0" GRAPH_CA_FILE="$DIR/graph.pem" \
  FASTAPI_UPSTREAM="http://127.0.0.1:$FA_PORT" RS_BIND="127.0.0.1:$RS_PORT" RATE_LIMIT_PER_MIN=0 \
    nohup ./target/release/pe-api-rs >"$DIR/rust.log" 2>&1 &
  echo $! >"$DIR/rust.pid"
)
wait_http "http://127.0.0.1:$RS_PORT/health" 30

cd "$ROOT"
PARITY_FASTAPI="http://127.0.0.1:$FA_PORT" \
PARITY_RUST="http://127.0.0.1:$RS_PORT" \
PARITY_ADMIN_TOKEN=test-admin \
PARITY_DB_URL="postgresql://postgres@localhost:$PORT/pe_parity" \
  python3 apps/api-rs/parity/run.py
