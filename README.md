# private-equity-ai

AI platform for private equity teams: ingest data-room documents, answer questions with citations that code verifies, build cited IC memo drafts, and track portfolio KPIs. Principle: a wrong number kills a deal, so every figure links to a source span and unverifiable output is refused, not softened.

Status: early but running. Private repo, planned to be open-sourced. Architecture, measured results and known gaps: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Setup and operations: [docs/RUNBOOK.md](docs/RUNBOOK.md).

## What works today
- Upload PDF, XLSX (cell-addressed, formulas kept, hidden sheets flagged) and UK Companies House iXBRL (balance-sheet arithmetic checked, failing filings marked UNRELIABLE).
- Tenant isolation: API keys, tenant filters in code and Postgres row-level security underneath.
- Facts are stored only if the quote is on the cited page and the number matches (`/facts`); IC memo drafts footnote every figure and compute derived ratios in code (`/memo`).
- Cross-check numbers against SEC XBRL, with restatements reported rather than hidden (`/xbrl/check`).
- Cited question answering with a verification gate and abstention (`/ask`; needs an LLM provider, not yet run against a real model).
- Portfolio KPIs that must link to a cited fact; hash-chained audit log; React UI for all of the above.

## What does not work yet
Dense retrieval (BM25 recall@10 is 0.57 on the sample set), OCR for scanned files in the app, user identities and roles, ethical walls, live market-data adapters (FactSet, PitchBook), Seedrs/Crowdcube import, Excel/PowerPoint export of memos. See the architecture doc for the full list.

## Quick start
```
export ADMIN_TOKEN=$(openssl rand -hex 16)
docker compose up --build          # api :8000, web :8080, Postgres (RLS), Redis
python scripts/smoke.py http://localhost:8000 $ADMIN_TOKEN
```
Local dev: `cd apps/api && pip install -e '.[dev]' && python -m pytest`; `cd apps/web && npm ci && npm run dev`.
