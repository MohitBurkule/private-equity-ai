#!/usr/bin/env bash
# Logical backup of the database (custom format) plus the ingest spool. Run from cron or a sidecar.
# Needs pg_dump and BACKUP_DATABASE_URL in libpq form (postgresql://user:pass@host:5432/db).
# Keeps the newest $KEEP backups. Test restores with scripts/restore.sh on a scratch database.
set -euo pipefail
: "${BACKUP_DATABASE_URL:?set BACKUP_DATABASE_URL (superuser or BYPASSRLS role, libpq URL: row-level security is forced even for the table owner)}"
DIR="${BACKUP_DIR:-./backups}"; KEEP="${KEEP:-14}"; TS="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$DIR"
pg_dump --format=custom --no-owner --file "$DIR/pe-$TS.dump" "$BACKUP_DATABASE_URL"
if [ -n "${SPOOL_DIR:-}" ] && [ -d "$SPOOL_DIR" ]; then tar -C "$SPOOL_DIR" -czf "$DIR/spool-$TS.tgz" .; fi
ls -1t "$DIR"/pe-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
ls -1t "$DIR"/spool-*.tgz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
echo "backup written: $DIR/pe-$TS.dump"
