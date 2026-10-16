# Runbook

## Configuration (environment variables)
| Variable | Purpose |
|---|---|
| `DATABASE_URL` | App connection. On Postgres this must be a non-superuser role without BYPASSRLS (startup refuses otherwise). Default is local SQLite for development only. |
| `MIGRATE_DATABASE_URL` | Owner role used at startup to create tables and apply row-level security policies. |
| `APP_DB_ROLE` | Role granted table privileges after migration (e.g. `pe_app`). |
| `ADMIN_TOKEN` | Enables `POST /admin/tenants` (header `X-Admin-Token`). Unset = tenant creation refused. Use a long random value; rotate by redeploying. |
| `SEC_USER_AGENT` | `"Company contact@example.com"`, required by SEC for `/xbrl/check`. |
| `LLM_PROVIDER`, `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Enable `/ask`. Without them `/ask` returns 503 and everything else works. Install extra: `pip install '.[llm]'`. |

## First tenant
```
curl -X POST $API/admin/tenants -H "X-Admin-Token: $ADMIN_TOKEN" -H 'content-type: application/json' -d '{"name":"My fund"}'
```
The response contains the API key once; only its hash is stored. Paste it into the web app's API key field.

## Database roles
`infra/db-init.sql` creates `pe_owner` and `pe_app` for compose. Change the placeholder passwords before any real use. Never connect the app as the owner or a superuser: row-level security would not protect you (the app refuses to start in that case).

## Health and integrity
- `GET /health` liveness.
- `GET /audit/verify` recomputes the tenant's audit hash chain; `ok:false` returns the first tampered row id.

## Known operational gaps
No backups or restore procedure yet, no key rotation or revocation endpoint, no rate limits, no malware scan on uploads, no request size limit in the API itself (nginx sets 200 MB), uploads are parsed in-process (a hostile PDF can consume memory), sessions of the web app keep the API key in sessionStorage. Treat as pre-production.
