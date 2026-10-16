# Production deployment guide

This covers what to change from the sample `docker-compose.yml` before real data goes in. Values here are checked against the code (`grep os.environ apps/api/app`); anything not listed is unsupported.

## Before first start

1. **Secrets.** Replace `change-me-app` and `change-me-owner` in `docker-compose.yml` (and `infra/db-init.sql`) with long random passwords. Set `ADMIN_TOKEN` to a long random value; it creates tenants and keys, keep it out of shell history and CI logs.
2. **Two database roles.** The API runs as `pe_app` (bound by row-level security). Migrations run as `pe_owner` via `MIGRATE_DATABASE_URL`. Never point `DATABASE_URL` at a superuser: that would bypass tenant isolation.
3. **TLS.** The compose file serves plain HTTP. Put a reverse proxy (Caddy, nginx, a cloud load balancer) in front, terminate TLS there, and publish only 443. Do not expose ports 8000, 5432 or 6379.
4. **Redis.** Set `REDIS_URL` when running more than one API replica, otherwise each replica keeps its own rate-limit bucket. If Redis is down the API falls back to a per-replica limit rather than failing.
5. **Spool volume.** `SPOOL_DIR` must be a volume shared by all replicas that run background ingest, and included in backups until jobs finish.

## Settings

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | App connection (role `pe_app`) |
| `MIGRATE_DATABASE_URL` | Owner connection used at start-up for migrations |
| `APP_DB_ROLE` | Role granted table access after migration |
| `ADMIN_TOKEN` | Tenant and key administration |
| `REDIS_URL` | Shared rate limit |
| `RATE_LIMIT_PER_MIN` | Requests per key per minute |
| `MAX_UPLOAD_BYTES`, `MAX_ARCHIVE_UNCOMPRESSED_BYTES` | Upload and zip limits |
| `INGEST_WORKERS` | Background ingest threads |
| `SCAN_COMMAND` | Optional virus-scan hook run on each upload |
| `OCR_ENABLED` | Scanned-page OCR |
| `LLM_PROVIDER`, `ANTHROPIC_MODEL` | Model for /ask, /ddq and extraction; without a provider those return 503 |
| `SEC_USER_AGENT` | Required by SEC for `/sec/filings` |
| `COMPANIES_HOUSE_API_KEY` | Free key for `/uk/company/{number}/accounts` |

## Operating

- **Health.** `GET /health` for load balancer checks.
- **Request tracing.** Every response carries `X-Request-ID` (the inbound value if it is 1 to 64 characters of letters, digits, `.`, `_`, `-`; otherwise generated). Each request writes one JSON line to stdout on the `pe.access` logger: request id, method, path, status, milliseconds. Query strings, headers and bodies are never logged. Quote the id when reporting a problem.
- **Audit log.** `GET /audit/verify` checks the per-tenant hash chain; run it on a schedule and alert on `ok: false`.
- **Backups.** `scripts/backup.sh` and `scripts/restore.sh`, then `scripts/restore_check.py`. The dump role needs superuser or BYPASSRLS. Test a restore before you need one.
- **Stuck jobs.** `POST /admin/jobs/requeue` after a crash or deploy.
- **Upgrades.** Migrations run at start-up from the owner connection. Take a backup first; downgrades are provided but data written by newer code is not guaranteed to survive them.

## Known limits

No single sign-on yet (API keys per tenant with roles and deal walls). No Elasticsearch/OpenSearch; search is in-process. Dense retrieval and reranking need model access that has not been set up.
