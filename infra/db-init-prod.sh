#!/bin/sh
# Runs once on first Postgres start in the production stack. Creates the two roles with passwords taken from
# the environment, so no password lives in a checked-in file. pe_owner owns the schema and runs migrations;
# pe_app serves requests and is bound by row-level security.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_pw="$PE_OWNER_DB_PASSWORD" -v app_pw="$PE_APP_DB_PASSWORD" <<'SQL'
CREATE ROLE pe_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE pe_app LOGIN PASSWORD :'app_pw' NOSUPERUSER NOBYPASSRLS;
ALTER DATABASE pe OWNER TO pe_owner;
GRANT ALL ON SCHEMA public TO pe_owner;
GRANT USAGE ON SCHEMA public TO pe_app;
CREATE EXTENSION IF NOT EXISTS vector;
SQL
