#!/usr/bin/env bash
# Restore a dump into TARGET_DATABASE_URL (owner role, libpq URL), then verify it.
# Usage: scripts/restore.sh backups/pe-<ts>.dump
# Never point this at a live production database by accident: it drops and recreates objects.
set -euo pipefail
DUMP="${1:?usage: restore.sh <dump file>}"
: "${TARGET_DATABASE_URL:?set TARGET_DATABASE_URL (superuser or BYPASSRLS role, libpq URL, scratch database)}"
pg_restore --clean --if-exists --no-owner --dbname "$TARGET_DATABASE_URL" "$DUMP"
# SQLAlchemy URL form for the checker
export RESTORE_CHECK_URL="${TARGET_DATABASE_URL/postgresql:\/\//postgresql+psycopg://}"
python "$(dirname "$0")/restore_check.py"
