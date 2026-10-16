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

## Keys, limits
- Rotate: `POST /admin/tenants/{tenant_id}/keys` (new key), switch clients, then `DELETE /admin/keys/{key_id}` for the old one (both with `X-Admin-Token`). Revoked keys get 401 immediately.
- `RATE_LIMIT_PER_MIN` (default 600 per tenant, 0 disables; in-memory, so per process: use a shared store before running several replicas). `MAX_UPLOAD_BYTES` (default 100 MB; nginx allows 200 MB, lower it to match).
- CSV/TSV uploads (for example a platform account export you download yourself) are stored as `row N: Header=value | ...` lines, 50 rows per page, so facts can cite a row. No platform layout is assumed.

## Data-room uploads
- `POST /documents` accepts PDF, XLSX, DOCX, PPTX, EML, CSV, iXBRL HTML and ZIP (detected by content). ZIPs and emails expand into one document per file; names keep the folder path (`Legal/cim.docx`, `thread.eml/memo.docx`). Response lists `documents` and `skipped` (name + reason); nothing is dropped silently.
- Limits: 2000 files, `MAX_ARCHIVE_UNCOMPRESSED_BYTES` (1 GB), nesting depth 3. Encrypted members, path-escaping names and size-mismatched members are skipped with a reason. A `deal` tag applies to every member.
- DOCX has no real pages: text is cut into ~3000-char chunks labelled by the nearest heading, so a citation page is a chunk, not a printed page. Legacy .doc/.ppt/.msg are not supported. No malware scan yet.

## Roles and deal walls (ethical walls)
- `POST /admin/tenants/{id}/keys` body `{"role": "admin|analyst|viewer", "deals": ["alpha"]}`. First key of a tenant is admin, unrestricted. `deals` omitted = sees every document; `deals: []` = sees nothing.
- A walled key sees only documents tagged with its deals (upload with form field `deal`; walled keys must set an in-scope deal). Untagged documents are hidden from walled keys. Facts, memos, KPIs, search and /ask are filtered the same way, and a model citation of a walled document is rejected.
- viewer is read-only. Audit events record `key:<key_id>` as actor.
- Enforced in the app layer; Postgres RLS is tenant-level only. Uploading identical bytes already stored under another deal returns 409 (reveals that the content exists). Changing a document's deal after upload is not supported yet. Keys are still service keys: no per-person identity or OIDC yet.

## Known operational gaps
No backups or restore procedure yet, no malware scan on uploads, no per-person identity (OIDC), uploads are parsed in-process (a hostile PDF can consume memory), sessions of the web app keep the API key in sessionStorage. Treat as pre-production.
