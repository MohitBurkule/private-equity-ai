# private-equity-ai

AI platform for private equity teams: ingest data-room documents, answer questions with citations that code verifies, build cited IC memo drafts, and track portfolio KPIs. Principle: a wrong number kills a deal, so every figure links to a source span and unverifiable output is refused, not softened.

Status: early but running. Private repo, planned to be open-sourced. Architecture, measured results and known gaps: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); diagrams (database, components, deployment): [docs/DIAGRAMS.md](docs/DIAGRAMS.md). Setup and operations: [docs/RUNBOOK.md](docs/RUNBOOK.md).

## What it does
An analyst loads deal documents, searches them, and every number in the output links to a quote on a source page. Facts that cannot be verified are refused. 

Screenshots are in the gallery under [Screenshots](#screenshots).

Known rough edges: `/ask` and auto-extraction need an LLM key and have not run against a real model.

## What works today
- Upload PDF (text layer, or OCR for scans with values flagged for human confirmation), XLSX (cell-addressed, formulas kept, hidden sheets flagged) and UK Companies House iXBRL (balance-sheet arithmetic checked, failing filings marked UNRELIABLE).
- Tenants, roles (admin, member, viewer), API keys, per-deal ethical walls; Postgres row-level security underneath; hash-chained audit log; request ids, JSON access log, Prometheus `/metrics`.
- Facts are stored only if the quote is on the cited page and the number matches (`/facts`); reviewer queue for unverified and OCR facts. IC memo drafts footnote every figure, compute derived ratios in code, and export to Word and PowerPoint (`/memo`, `/memo.docx`, `/memo.pptx`).
- Cited question answering with a verification gate and abstention (`/ask`, batch `/ddq`; needs an LLM provider, not yet run against a real model).
- Calculators that never default a missing input: LTM, net debt, NWC, table tie-out and sum checks, share-ledger reconciliation, fund metrics (DPI, TVPI, XIRR, vintage cohorts), exit waterfall.
- Deals pipeline with a DD request tracker; portfolio KPIs that must link to a cited fact, covenant tests, portfolio report (JSON and Word).
- Data sources: SEC XBRL cross-check and filings list; Companies House filing list, officers and PSC (keyed API), PSC snapshot extractor, Basic Company Data parser, SH01 capital-form reader; holdings CSV import (Seedrs, Crowdcube and similar exports, header-mapped); market quotes from Yahoo, Stooq and FactSet (`/market/quote`); PitchBook, Crowdcube and Seedrs/Republic CSV exports turned into cited facts (`/documents/{id}/vendor-facts`).
- Eval dashboard in the UI; React UI for all of the above.

## Screenshots

Captured from the running UI. The first screens are from a real local run with demo data (Apple Q3 FY23 10-Q). The walkthrough screens (valuation, access report, memo charts, snapshot) use SYNTHETIC demo data, plus XPO facts cited from its FY2025 10-K.

| | |
|---|---|
| ![Chat home with a proactive inbox](docs/screenshots/03-chat-answer.png) | ![Click any citation to read the source page](docs/screenshots/04-chat-source-drawer.png) |
| Chat home with a proactive inbox | Click any citation to read the source page |
| ![Interactive dashboards](docs/screenshots/08-dashboards.png) | ![Deals and diligence tracker](docs/screenshots/06-deals.png) |
| Interactive dashboards | Deals and diligence tracker |
| ![Portfolio: cited KPIs and the covenant card, which says when no tests have run](docs/screenshots/07-portfolio.png) | ![Documents, search, memo](docs/screenshots/05-documents.png) |
| Covenant breach from cited facts | Documents, search, memo |
| ![Comps with a cited implied range](docs/screenshots/11-comps.png) | ![Integrations catalog and import](docs/screenshots/12-integrations.png) |
| Comps with a cited implied range | Integrations catalog and import |
| ![Firm profile: rules found in your documents](docs/screenshots/13-firm-profile.png) | ![Workflows built from the agent tools](docs/screenshots/14-workflows.png) |
| Firm profile: rules found in your documents | Workflows built from the agent tools |
| ![Acquisition target map, filter by sector, country, revenue](docs/screenshots/15-targets.png) | ![API key sign-in](docs/screenshots/01-key-screen.png) |
| Acquisition target map, filter by sector, country, revenue | API key sign-in |
| ![Chat home](docs/screenshots/02-home-chat-inbox.png) | ![Review queue for unverified facts](docs/screenshots/09-review.png) |
| Chat home | Review queue for unverified facts |
| ![Answer evals](docs/screenshots/10-evals.png) | ![Deck upload](docs/screenshots/17-deck-upload.png) |
| Answer evals | Deck upload |
| ![IC memo draft](docs/screenshots/18-memo-deck-3m.png) | ![Highlighted source page](docs/screenshots/21-source-page-highlight.png) |
| IC memo draft | Highlighted source page |
| ![Highlighted filing page](docs/screenshots/22-filing-page-highlight.png) | ![Home brief, dark theme](docs/screenshots/23-home-brief-dark.png) |
| Highlighted filing page | Home brief, dark theme |
| ![Home brief, light theme](docs/screenshots/24-home-brief-light.png) | ![Command palette](docs/screenshots/25-command-palette-dark.png) |
| Home brief, light theme | Command palette |
| ![Portfolio, dark theme](docs/screenshots/26-portfolio-dark.png) | ![Review queue](docs/screenshots/27-review-queue.png) |
| Portfolio, dark theme | Review queue |
| ![Covenant tracker](docs/screenshots/28-covenant-tracker.png) | ![LBO returns](docs/screenshots/29-lbo-returns.png) |
| Covenant tracker | LBO returns |
| ![LBO history](docs/screenshots/33-lbo-history.png) | ![Integration status](docs/screenshots/30-integrations-status.png) |
| LBO history | Integration status |
| ![Sourcing search](docs/screenshots/31-sourcing-search.png) | ![Candidate watch](docs/screenshots/32-candidate-watch.png) |
| Sourcing search | Candidate watch |
| ![Memo screen](docs/screenshots/34-memo-screen.png) | ![Alert emails in the local inbox](docs/screenshots/16-mailpit-inbox.png) |
| Memo screen | Alert emails in the local inbox |
| ![Dashboards with seeded demo data](docs/screenshots/19-dashboards-seeded.png) | ![Deal snapshot card above the workspace](docs/screenshots/21-deal-snapshot.png) |
| Dashboards with seeded demo data | Deal snapshot card above the workspace |
| ![Valuation rounds, each linked to its source line](docs/screenshots/16-valuation-history.png) | ![Admin report of logged actions on one deal](docs/screenshots/17-deal-access-report.png) |
| Valuation rounds, each linked to its source line | Admin report of logged actions on one deal |
| ![IC memo run: steps ok, skipped steps show why](docs/screenshots/22-memo-run.png) | ![Memo revenue chart, FY2023–25, with source line](docs/screenshots/18-memo-revenue-chart.png) |
| IC memo run: steps ok, skipped steps show why | Memo revenue chart, FY2023–25, with source line |
| ![Memo EBITDA (Adjusted) chart, with source line](docs/screenshots/19-memo-ebitda-chart.png) | ![Memo margins and net debt / EBITDA, derived from cited facts](docs/screenshots/20-memo-margins-leverage-chart.png) |
| Memo EBITDA (Adjusted) chart, with source line | Memo margins and net debt / EBITDA, derived from cited facts |
| ![Deal workspace at 390px: documents and extract buttons stack](docs/screenshots/35-phone-workspace.png) | ![IC review at 390px](docs/screenshots/36-phone-ic-review.png) |
| Deal workspace at phone width | IC review at phone width |

## What does not work yet
- Dense retrieval (BM25 recall@10 is 0.57 on the sample set; no model downloads in the build sandbox).
- A PitchBook API client (only its CSV export is read), and real keyed responses for FactSet and Companies House: test fixtures are synthetic until someone with a licence or key saves real responses.
- Seedrs/Crowdcube/PitchBook header presets are tested on made-up layouts, not real exports. No scraping, by design: terms of service, so only files the user downloads.
- Docker compose has never been run end to end in the build sandbox (CI runs the API on Postgres).
- Real-LLM evaluation of `/ask`, `/ddq` and extraction (no API key during the build).
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full list.

## Quick start

### See it in one command (no Postgres, no Docker)

```
make demo
```

Asks once for an SEC User-Agent (your name and contact) so live EDGAR search works. Leave it blank to skip; nothing
is written to the repo. Starts the API on SQLite, seeds it with three real 10-K filings (3M, Hertz, Sotera) when `data/demo/edgar`
or `DATA_DIR` holds them, builds the web UI, and prints the URL and API key. Open http://localhost:5173 and
paste the key. Stop with Ctrl+C. Logs go to a temp folder, or to `DEMO_DIR` if you set it.

For Postgres and the full stack, use the Docker steps below.
```
export ADMIN_TOKEN=$(openssl rand -hex 16)
docker compose up --build          # api :8000, web :8080, Postgres (RLS), Redis
python scripts/smoke.py http://localhost:8000 $ADMIN_TOKEN
python scripts/seed_demo.py http://localhost:8000 $ADMIN_TOKEN   # demo tenant + API key for the UI
```
Local dev: `cd apps/api && pip install -e '.[dev]' && python -m pytest`; `cd apps/web && npm ci && npm run dev`.
