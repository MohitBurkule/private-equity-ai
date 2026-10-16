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
- `RATE_LIMIT_PER_MIN` (default 600 per tenant, 0 disables). Without `REDIS_URL` the limit is a per-process token bucket; with `REDIS_URL` (compose sets it) it is a shared one-minute window across replicas (up to 2x burst at a window edge) and falls back to the local bucket if Redis is down. `MAX_UPLOAD_BYTES` (default 100 MB; nginx allows 200 MB, lower it to match).
- CSV/TSV uploads (for example a platform account export you download yourself) are stored as `row N: Header=value | ...` lines, 50 rows per page, so facts can cite a row. No platform layout is assumed.

## Data-room uploads
- `POST /documents` accepts PDF, XLSX, DOCX, PPTX, EML, CSV, iXBRL HTML and ZIP (detected by content). ZIPs and emails expand into one document per file; names keep the folder path (`Legal/cim.docx`, `thread.eml/memo.docx`). Response lists `documents` and `skipped` (name + reason); nothing is dropped silently.
- Limits: 2000 files, `MAX_ARCHIVE_UNCOMPRESSED_BYTES` (1 GB), nesting depth 3. Encrypted members, path-escaping names and size-mismatched members are skipped with a reason. A `deal` tag applies to every member.
- DOCX has no real pages: text is cut into ~3000-char chunks labelled by the nearest heading, so a citation page is a chunk, not a printed page. Legacy .doc/.ppt/.msg are not supported. No malware scan yet.

## Covenant alerts
- `POST /portfolio/companies/{id}/covenants {kpi_metric, operator "<="|">=", threshold_fact_id}`: the threshold must be a verified, cited fact (for example one accepted from the `debt` extraction), never a typed number. `GET .../covenants` tests every current KPI observation of that metric: `ok`, `breach` (with `headroom_pct`, negative = over) or `unit_mismatch`; `breaches` is the alert list. Pull-based for now: no email or push notification yet.

## Contradictions and DD requests
- Memo exports: `GET /memo` (text), `/memo.docx`, `/memo.pptx`; all use verified facts only and carry a draft notice and a sources list.
- `GET /facts/conflicts[?entity=]`: same entity, metric, period, basis and unit with different values across facts (rejected ignored). Reports spread and `likely_rounding` (under 0.5%); never picks a winner. It only sees facts that were created, so it is as complete as the extraction and review work.
- DD list: `POST /dd/requests/seed {deal, categories?}` (standard template: financial, commercial, legal, tax, hr, it_esg), `POST /dd/requests`, `GET /dd/requests?deal=&status=`, `PATCH /dd/requests/{id}` (status open/received/waived, or `document_id` which must belong to the same deal and marks it received), `GET /dd/summary?deal=` (percent complete, missing items). Walled keys only see and change their own deals.

## Background ingest
- `POST /documents/async` (same fields and walls as `/documents`) returns 202 `{job_id}`; poll `GET /jobs/{id}` (status queued/running/done/failed, stage, attempts, result with `documents` and `skipped`). `GET /jobs` lists the latest 100; walled keys see only their own jobs.
- Env: `INGEST_WORKERS` (2), `SPOOL_DIR` (system temp; put it on a persistent volume), `SCAN_COMMAND` (for example `clamdscan --no-summary`; the file path is appended; non-zero exit fails the job and removes the file; unset = no scan).
- Unexpected errors retry up to 3 times. After a restart queued jobs are re-run at startup (`POST /admin/jobs/requeue` does it on demand). Workers run inside the API process, so a heavy PDF still competes with requests; move to a separate worker container when load needs it.

## Structured extraction
- `GET /extract/schemas` lists schemas (debt, customer_concentration, arr, ebitda_bridge). `POST /documents/{id}/extract` `{schema_name, entity, period}` needs `LLM_PROVIDER`. The model proposes value, page and quote per field; code accepts only if the quote is on that page and the value is a number printed in it (USD fields may use the page's own "in millions/thousands" scale; the model cannot supply a scale). Masked terms (`[***]`) come back as `redacted`, never filled.
- Accepted values are stored with status `auto`: not in memos or calc until a person accepts them via `POST /facts/{id}/review`. Never run against a real model yet; the golden text set (25 items) is for that evaluation.

## Roles and deal walls (ethical walls)
- `POST /admin/tenants/{id}/keys` body `{"role": "admin|analyst|viewer", "deals": ["alpha"]}`. First key of a tenant is admin, unrestricted. `deals` omitted = sees every document; `deals: []` = sees nothing.
- A walled key sees only documents tagged with its deals (upload with form field `deal`; walled keys must set an in-scope deal). Untagged documents are hidden from walled keys. Facts, memos, KPIs, search and /ask are filtered the same way, and a model citation of a walled document is rejected.
- viewer is read-only. Audit events record `key:<key_id>` as actor.
- Enforced in the app layer; Postgres RLS is tenant-level only. Uploading identical bytes already stored under another deal returns 409 (reveals that the content exists). Changing a document's deal after upload is not supported yet. Keys are still service keys: no per-person identity or OIDC yet.

## Backup and restore
- `scripts/backup.sh` (needs `BACKUP_DATABASE_URL`, a superuser or BYPASSRLS role in libpq form; `BACKUP_DIR`, `KEEP`, optional `SPOOL_DIR`) writes a custom-format `pg_dump` plus a spool tarball and prunes old ones. The `pe_owner` and `pe_app` roles cannot dump: row-level security is forced for everyone, which is intended. In the compose stack use the `pe` superuser.
- `scripts/restore.sh <dump>` (needs `TARGET_DATABASE_URL`, same kind of role, a scratch database) restores and then runs `scripts/restore_check.py`: per-tenant document and fact counts, orphaned fact sources, and the audit hash chain. Exit 1 on any problem; a tampered audit row is detected (drill done: edited one row after restore, check failed as expected).
- Do a restore drill on a scratch database regularly; an untested backup is not a backup. Compose now keeps the ingest spool on the `spool` volume so queued jobs survive a container restart. Point-in-time recovery (WAL archiving) is not set up.

## Known operational gaps
No point-in-time recovery, no per-person identity (OIDC), uploads are parsed in-process (a hostile PDF can consume memory), sessions of the web app keep the API key in sessionStorage. Treat as pre-production.

## Deals, DDQ answering, market data

- `POST /deals`, `GET /deals`, `PATCH /deals/{name}`: stage (sourcing, screening, dd, ic, signed, closed, passed), note, document and open-DD counts. Walled keys cannot create deals.
- `POST /ddq` with `{"questions": [...]}` (1 to 200): each question is answered alone with verified, cited claims only. `needs_human` is true for anything abstained, failed or empty. No answer is ever filled in without a source.
- `app/marketdata.py`: `Provider` protocol and `CsvProvider` (columns symbol, price, currency, as_of). Paid feeds implement the protocol. Missing symbols raise `NoData`.

## Portfolio report

`GET /portfolio/report` (JSON) and `/portfolio/report.docx`: covenant alerts first, then each company's current KPIs with source document and page. Only facts the key may see are used.

See `docs/DEPLOY.md` for production settings and request tracing.

## Dropped table cells

Some filing text drops blank cells, so a row has fewer values than columns. `POST /calc/tieout` takes the short rows (null = printed dash), the base row and the printed total row, tries every order-preserving placement and keeps only those where each column adds up. One survivor is `resolved`; several are `ambiguous`; none is `no_solution`; too many to try is `too_large`. Verified on the Alliance Laundry 424B4 Adjusted EBITDA bridge (see `tests/test_tieout.py`).

## Sum checks

`POST /calc/sumcheck` compares printed parts with a printed total and returns the exact gap. Verified on the Alliance Laundry 600-share inconsistency and the Netskope Class B share count (`tests/test_sumcheck.py`).

## Companies House

`GET /uk/company/{number}/accounts` lists accounts filings with document links. Needs `COMPANIES_HOUSE_API_KEY` (503 without). Tests use a SYNTHETIC fixture (`tests/fixtures/ch_filing_history_SYNTHETIC.json`); replace it with a saved real response once a key exists. Add the variable to `docs/DEPLOY.md` settings.

## Holdings import (Seedrs/Republic, Crowdcube, any CSV)

`POST /holdings/import` (multipart: `file`, `platform`, optional `currency`, optional `mapping` JSON) imports a holdings export the user downloaded. No scraping and no assumed platform layout: columns are found by common names or by your mapping; currency is never assumed; dates must be ISO. Bad rows are rejected with their line number. Every holding keeps its source document and line. Re-importing the same file returns 409. `GET /holdings` lists them. Walled keys cannot import or list. The test CSV is a made-up layout, not a real platform export; send a real one to add a named mapper.

## Share ledger (SH01, SH02, SH19)

`POST /calc/share-ledger` takes an opening share total and the capital events read from Companies House forms (allot, statement, consolidate) and keeps one running total. Same-day forms stated against the same prior base are combined, not chained; a consolidation must start from the running total and gives the ratio; a form that fits none of these is listed as unreconciled and does not move the total. Verified on the Monzo numbers in the golden set (same-day SH01s, SH19 to SH01 to SH02 chain). Reading the numbers off the scanned PDFs needs OCR or a vision model, which is not available in the build environment; until then a person or the extraction pipeline supplies the values and cites the page.

## Fund metrics

`POST /calc/fund-metrics` returns DPI, RVPI, TVPI and XIRR from dated flows (paid in negative, distributions positive), a NAV and an as-of date. No IRR is returned when the flows cannot produce one; the reason is in `irr_note`. Inputs are the caller's; link them to cited facts when they come from reports.

## Evals dashboard

`python evals/record.py DATA_DIR [suite ...]` (with `PE_API_URL` and `PE_API_KEY`) runs the golden, retrieval, uk and xbrl suites and posts each result to `POST /evals`; the Evals tab shows the latest run per suite against the previous one and lists misses. A suite that cannot run is reported and not recorded. Last local runs: golden 9 of 9 rows found, uk 45 of 45 correct, xbrl 118 of 118 match (4 items have no inline/API pair and are counted separately).

## Retrieval choice

Search uses BM25. A hybrid index (BM25 plus char-trigram ranker, fused with RRF) exists in `app/hybrid.py` but is not wired in: on the 14 FinanceBench questions whose filings are available it gave recall@1 0.143 / @3 0.429 / @5 0.429 / @10 0.5 against BM25 0.143 / 0.286 / 0.5 / 0.571, so it is not clearly better and n is small. Dense rankers plug in through the `Ranker` protocol once model access exists; wire hybrid only if the eval shows a gain on a larger set.

## Reading SH01 forms

`GET /documents/{id}/capital-form` reads an electronic SH01 from the stored pages: company number, allotment dates, class rows (number, nominal, paid, unpaid), statement-of-capital rows and totals, each with page and verbatim line. Scanned forms need OCR at upload (`OCR_ENABLED`, the project's `ocr` extra); their values are flagged `ocr: true` and need a person to confirm them. Digits OCR turns into letters are reported unreadable, never repaired. Checked on the Monzo forms from the golden set: the text form (15,000,000 allotted, total 41,807,801) and the OCR-read form (15,519,568 allotted, total 26,753,982), which together with the earlier form give the combined 26,807,801 through `/calc/share-ledger`.

## Exit waterfall

`POST /calc/waterfall` splits an exit value across preferred classes and common: seniority ranks (equal ranks pro rata), liquidation-preference multiple, participating with optional cap, and conversion to common when that pays more. Payouts add up to the exit value to the cent. It does NOT apply dividends, anti-dilution adjustments, option exercise prices or management carve-outs; read those from the charter and treat the result as a first pass.
