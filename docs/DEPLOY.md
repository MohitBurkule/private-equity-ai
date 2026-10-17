# Production deployment guide

This covers what to change from the sample `docker-compose.yml` before real data goes in. Values here are checked against the code (`grep os.environ apps/api/app`); anything not listed is unsupported.

## Before first start

1. **Secrets.** Use `docker-compose.prod.yml`, which takes every password from the environment. See [SECRETS.md](SECRETS.md). Never use the `change-me-*` values from the dev compose file. Set `ADMIN_TOKEN` to a long random value; it creates tenants and keys, keep it out of shell history and CI logs.
2. **Two database roles.** The API runs as `pe_app` (bound by row-level security). Migrations run as `pe_owner` via `MIGRATE_DATABASE_URL`. Never point `DATABASE_URL` at a superuser: that would bypass tenant isolation.
3. **TLS.** The compose file serves plain HTTP. Put a reverse proxy (Caddy, nginx, a cloud load balancer) in front, terminate TLS there, and publish only 443. Do not expose ports 8000 or 5432.
4. **Rate limit across replicas.** The default limit is per process. With more than one API replica, set `RATE_LIMIT_BACKEND=postgres` so the count is shared through the database (migration 0041 creates `rate_window`). `REDIS_URL` is still read for older deployments, but the stack is PostgreSQL-only, so prefer the database.
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
- **Metrics.** `GET /metrics` (header `X-Admin-Token`) returns Prometheus text: request counts by method, route template and status class, and summed latency in ms. Counts are per process and reset on restart, so scrape every replica. No tenant, key or URL parameter appears in the labels.
- **Audit log.** `GET /audit/verify` checks the per-tenant hash chain; run it on a schedule and alert on `ok: false`.
- **Backups.** `scripts/backup.sh` and `scripts/restore.sh`, then `scripts/restore_check.py`. The dump role needs superuser or BYPASSRLS. Test a restore before you need one.
- **Stuck jobs.** `POST /admin/jobs/requeue` after a crash or deploy.
- **Upgrades.** Migrations run at start-up from the owner connection. Take a backup first; downgrades are provided but data written by newer code is not guaranteed to survive them.

## Known limits

No single sign-on yet (API keys per tenant with roles and deal walls). No Elasticsearch/OpenSearch; search is in-process. Dense retrieval and reranking need model access that has not been set up.

## Alerts

`deploy/monitoring/alerts.yml` holds Prometheus rules for the API: target down, 5xx ratio, auth-failure spike, rate-limit pressure. A test fails if a rule uses a metric the app does not export. Pair with `GET /audit/verify` on a schedule (see above), since no metric covers audit-chain integrity.
