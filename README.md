# private-equity-ai

AI platform for private equity teams: ingest data-room documents, answer questions with citations that code verifies, build cited IC memo drafts, and track portfolio KPIs. Principle: a wrong number kills a deal, so every figure links to a source span and unverifiable output is refused, not softened.

Status: early but running. Private repo, planned to be open-sourced. Architecture, measured results and known gaps: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); diagrams (database, components, deployment): [docs/DIAGRAMS.md](docs/DIAGRAMS.md). Setup and operations: [docs/RUNBOOK.md](docs/RUNBOOK.md).

## What works today
- Upload PDF (text layer, or OCR for scans with values flagged for human confirmation), XLSX (cell-addressed, formulas kept, hidden sheets flagged) and UK Companies House iXBRL (balance-sheet arithmetic checked, failing filings marked UNRELIABLE).
- Tenants, roles (admin, member, viewer), API keys, per-deal ethical walls; Postgres row-level security underneath; hash-chained audit log; request ids, JSON access log, Prometheus `/metrics`.
- Facts are stored only if the quote is on the cited page and the number matches (`/facts`); reviewer queue for unverified and OCR facts. IC memo drafts footnote every figure, compute derived ratios in code, and export to Word and PowerPoint (`/memo`, `/memo.docx`, `/memo.pptx`).
- Cited question answering with a verification gate and abstention (`/ask`, batch `/ddq`; needs an LLM provider, not yet run against a real model).
- Calculators that never default a missing input: LTM, net debt, NWC, table tie-out and sum checks, share-ledger reconciliation, fund metrics (DPI, TVPI, XIRR, vintage cohorts), exit waterfall.
- Deals pipeline with a DD request tracker; portfolio KPIs that must link to a cited fact, covenant tests, portfolio report (JSON and Word).
- Data sources: SEC XBRL cross-check and filings list; Companies House filing list, officers and PSC (keyed API), PSC snapshot extractor, Basic Company Data parser, SH01 capital-form reader; holdings CSV import (Seedrs, Crowdcube and similar exports, header-mapped); market quotes from Yahoo, Stooq and FactSet (`/market/quote`).
- Eval dashboard in the UI; React UI for all of the above.

## What does not work yet
- Dense retrieval (BM25 recall@10 is 0.57 on the sample set; no model downloads in the build sandbox).
- PitchBook, and real keyed responses for FactSet and Companies House: adapters exist but their test fixtures are synthetic until someone with a licence or key saves real responses.
- Seedrs/Crowdcube import is tested on a made-up layout, not a real export.
- Docker compose has never been run end to end in the build sandbox (CI runs the API on Postgres).
- Real-LLM evaluation of `/ask`, `/ddq` and extraction (no API key during the build).
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full list.

## Quick start
```
export ADMIN_TOKEN=$(openssl rand -hex 16)
docker compose up --build          # api :8000, web :8080, Postgres (RLS), Redis
python scripts/smoke.py http://localhost:8000 $ADMIN_TOKEN
python scripts/seed_demo.py http://localhost:8000 $ADMIN_TOKEN   # demo tenant + API key for the UI
```
Local dev: `cd apps/api && pip install -e '.[dev]' && python -m pytest`; `cd apps/web && npm ci && npm run dev`.
