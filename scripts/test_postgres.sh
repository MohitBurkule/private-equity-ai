#!/usr/bin/env bash
# Run the API test suite against a throwaway Postgres 18 cluster, no Docker needed.
# Binaries come from the embedded-postgres pip package. The cluster runs as a non-root OS user
# (initdb refuses root): set PG_RUN_AS to a user that exists, e.g. PG_RUN_AS=pgrunner.
# The tests use a non-superuser, non-RLS-bypass app role, like production (verify_app_role).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PG_TEST_PORT:-55432}"
DIR="${PG_TEST_DIR:-$(mktemp -d /tmp/pe-pg-XXXXXX)}"
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

stop() { pg "$BIN/pg_ctl" -D "$DIR/data" -m fast stop >/dev/null 2>&1 || true; }
cleanup() { stop; if [ -z "${PG_TEST_DIR:-}" ]; then rm -rf "$DIR"; fi; }
trap cleanup EXIT

pg "$BIN/initdb" -D "$DIR/data" -U postgres --auth=trust --encoding=UTF8 --locale=C >"$DIR/initdb.log" 2>&1
pg "$BIN/pg_ctl" -D "$DIR/data" -l "$DIR/pg.log" -w -o "-p $PORT -k $DIR" start >/dev/null
pg "$BIN/psql" -h localhost -p "$PORT" -U postgres -v ON_ERROR_STOP=1 -q <<SQL
CREATE ROLE app_user LOGIN NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE pe_test OWNER postgres ENCODING UTF8 TEMPLATE template0;
SQL

cd "$ROOT/apps/api"
DATABASE_URL="postgresql+psycopg://app_user@localhost:$PORT/pe_test" \
MIGRATE_DATABASE_URL="postgresql+psycopg://postgres@localhost:$PORT/pe_test" \
  APP_DB_ROLE=app_user \
  python3 -m pytest -q -p no:cacheprovider "$@"
