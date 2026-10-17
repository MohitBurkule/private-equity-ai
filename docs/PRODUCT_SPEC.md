# Product spec and master tracker

Status vs repo main (2026-10-16). BUILT = in main with tests. PARTIAL = some of it. MISSING = none.
Owner threads: integrations, PDF pipeline, comps/valuation + workflows, UI. This file is the tracker; update the row when a PR merges.

## 1. Is it "a chatbot with RAG and tools"?

Plainly: no, but the chat box is one door into it. A chatbot with RAG answers questions about text. A PE firm needs work done: a screened target list, a tied-out IC memo, a quarterly portfolio pack, a clause table across 200 contracts, on a schedule, in the firm's house style, with every number traceable. That needs four layers, and RAG is only part of one.

```
 Firm memory      what the firm does and prefers (cited), prior deals, people, templates
      |
 Agent            plans, picks tools, asks the user only when blocked, refuses to guess
      |
 Domain workflows fixed, tested recipes: IC memo, QoE, comps, legal review, LP pack, screening
      |
 Tools            search, ask (cited), extract, calc, market data, connectors, doc generation
      |
 Trust layer      fact gate, citation verifier, conflict detector, ACL/RLS, audit chain
```

Product shape (user, 2026-10-16): a chat-first system that is also proactive. Chat gives cited answers on demand. Background agents run on schedules and events and push findings to an inbox and email: covenant breaches, new SEC/CH filings for watched companies, portfolio KPI changes, new targets matching the firm's screening criteria, weekly briefs. Same tools, same workflows, same citation gate for both.

Rules that follow:
1. Workflows are code with typed steps. The LLM fills in judgment steps only. Arithmetic is always code.
2. The agent may call any tool but cannot emit a number without a verified source. Failing claims are dropped (already enforced in `answer.py`).
3. Firm memory is a profile of cited values, not free chat history. A value without a source quote is rejected.
4. Every run is stored (goal, steps, tool args, outputs) so it can be audited and replayed.
5. Scheduled runs use the same workflows with a cron trigger.

Target modules: `firm_knowledge.py` (profile), `agent.py` (tool registry, workflow runner, bounded agent loop, run log). Workflows are registered from other modules.

## 2. Capability tracker

| # | Capability | Status | In repo / gap | Owner |
|---|---|---|---|---|
| 1 | Sourcing and screening of targets | PARTIAL | Deals + stages, UK CH/PSC feeds, PitchBook/Crowdcube/Seedrs export import, holdings. Criteria screen over the universe with a score (weighted share of criteria passing; unknown counts as not passed; firm weights per criterion via `weights`, unlisted = 1) and saved screens (`POST /targets/screens`, rerun `POST /targets/screens/{id}/run`). Firm-set weights: an accepted `screening_weights` rule (e.g. "sector: 2, revenue: 0") is the default; request `weights` override it, and the response cites the rule in `applied.weights_source`. Universe refresh on demand (`POST /targets/refresh`). Weights are editable on the Targets page (Screen panel); a blank weight defers to the firm rule. Universe refresh runs on demand and on a `universe_refresh` schedule. | workflows |
| 2 | Add-on search | PARTIAL | `GET /portfolio/companies/{id}/add-ons`: targets in the company's sector, minus owned companies (same matcher as seen-before), screened by the accepted revenue floor, unknown revenue flagged as review. Portfolio companies carry a SIC code (`sic`); a target with the same SIC matches even when its sector label differs (`matched_on: sic`). `POST /targets/refresh` re-pulls stored SEC and Companies House targets from their sources (live SEC submissions and facts; CH by number), updates rows in place, and reports refreshed, failed and dissolved counts; a dissolved company is never refreshed silently. A `universe_refresh` schedule runs the same refresh from `POST /workflows/run-due` and mails a count summary. Missing: refresh in the UI | workflows |
| 3 | Enterprise search (docs, email, data) | PARTIAL | Seen-before lookup across targets, portfolio and visible deals (#117). Scoped BM25 with hybrid dense retrieval and rerank (#162), ACL before ranking, eml/office/xlsx/pdf parse, source viewer. Saved searches rerun under the rerunner's own access (`POST /search/saved`, `GET /search/saved/{id}/run`). Missing: connectors (data rooms, SharePoint, Drive, Outlook), search over email and notes beyond parsed files, permission sync from source systems | PDF + integrations |
| 4 | IC materials | PARTIAL | Cited memo, DOCX + PPTX export, facts gate, accepted firm rules (LP tone, sign-off threshold, board cadence) quoted in the memo and report drafts. `POST /memo/versions` saves the draft as the next numbered version, with comments (`/memo/versions/{id}/comments`); `GET /memo/versions/diff` compares two saved versions; `POST /memo/diff` compares with text the reviewer sends. Whole-tenant keys only. Missing: firm templates, auto-pull from CRM/SharePoint | workflows |
| 5 | Trading comps | DONE | `POST /calc/comps` builds the table with each peer's multiples cited, and the implied range (quartiles). Downloads as DOCX and PPTX (`/calc/comps.docx`, `.pptx`). `/market/quote` (Yahoo, Stooq, FactSet), XBRL companyfacts, peer FX conversion (#300) | comps |
| 6 | Precedent transactions | PARTIAL | `GET /precedents/summary`: stated EV and multiples cited to page and sentence, medians only with 3+ deals. Missing: a curated deal dataset | comps |
| 7 | Legal review (NDA, SPA, covenants) | PARTIAL | Covenants table, extract schemas, cap table, share ledger, waterfall. Cited extraction rows (GAPS #7): covenant tests, debt tranches, cohort/ARR/churn, customer concentration, EBITDA bridges re-added with an inbox item on mismatch. Clause library catalogue (`GET /legal/clause-library`: key terms by document type, playbook positions). Each document's red flags apply the playbook (`/documents/{id}/legal-terms`). Missing: firm-specific clause text, red-flag table in the UI, full change-of-control/MFN/exclusivity extraction into the structured model (GAPS #7, #13) | workflows |
| 8 | Portfolio tracking | BUILT (core) | Companies, KPI observations, covenants, change report, DOCX report, fund metrics, cohorts | - |
| 9 | Scheduled workflows and proactive alerts (inbox, email) | PARTIAL | Alert inbox + covenant watcher (`/alerts`), workflow runs (`/agent`). Email digest (`/alerts/digest`, SMTP) and periodic scan (`ALERT_SCAN_INTERVAL_S`) built. Watchers: covenants, stalled deals and overdue DD (thresholds from accepted `deal_stall_days` and `dd_response_days` rules, defaults 30 and 14), firm leverage limit (accepted `leverage_limit` vs portfolio `net_leverage_x`), KPI overdue (accepted `kpi_reporting_cadence` vs newest KPI observation age). Filings: new 10-K/10-Q/8-K from EDGAR atom feed for targets with status `watching` (PATCH `/targets/{id}`), keyed by accession. Screening: new targets matching plain-words `sectors:` and `minimum revenue` in the accepted `deal_screening_criteria` rule, only when revenue is known. Proactive brief: `GET /alerts/brief?since=` counts what the system raised since a time, by kind and severity, critical first, each item with its sources. Workflow kind `daily_brief` mails it on schedule (quiet when nothing is new); the home Inbox shows the last 24 hours. Per-person digest: each signed-in person sets `PUT /me/digest` (email, least severe alert) and gets their own unsent alerts via `POST /me/digest/send`, watermarked per person. Per-person digest (`PUT /me/digest`, `POST /me/digest/send`) is scoped to the signed-in person's deals: a deal-scoped sign-in gets only deal and DD alerts for its own deals; alerts with no deal are left out of scoped digests. Missing: deal column on alerts (scope reads it from the title) | agent core |
| 10 | Document generation (decks, research, outreach emails) | PARTIAL | memo DOCX/PPTX, portfolio DOCX, outreach batch with a review queue (row 22). Missing: research report as a deck | workflows |
| 11 | Interactive dashboards | DONE | React app, KPI panels with a Board view (company by period, every cell cited). Target map filters by sector, country and revenue | UI |
| 12 | Integrations (FactSet, PitchBook, DealCloud, SharePoint, Outlook, Gmail, Drive, LinkedIn, Cap IQ) | PARTIAL | Cap IQ and PitchBook price adapters, unverified shape, env-configured (#116); LinkedIn export (#109); Intralinks/Datasite (#106).  FactSet quote, PitchBook export, Yahoo/Stooq, SEC, CH. Missing: OAuth connectors, DealCloud, SharePoint, Outlook, Drive | integrations |
| 13 | PDF processing | PARTIAL | Marker adapter, Camelot benchmark, golden accuracy floor (#113, #114, #115).  pdf text, OCR fallback, statement rows, SH01, iXBRL. Missing: layout/table models, chart reading | PDF |
| 14 | Data-conflict flags | BUILT (core) | `/facts/conflicts`, tie-out, sumcheck. Missing: CIM vs DD report vs annual report doc-level pairing UI | workflows |
| 15 | Benchmarking vs live data | PARTIAL | XBRL cross-check, quotes. Sector benchmark table with every peer and source (`/targets/benchmark`). SEC peers auto-picked by SIC and 0.5x to 2x revenue band, median shown (`GET /targets/{id}/sic-peers`). Missing: peers beyond SIC and size, live refresh of peer revenue | comps |
| 16 | Workspaces (multi-deal, team) | PARTIAL | Deals, API-key roles, per-deal ACL, OIDC SSO with tenant, role and deal claims (#205, #212, #215), per-person digest. Ethical walls are deal scopes (a walled key sees only its deals, `acl.py`). MNPI flag on a deal hides its documents, MNPI alerts and digest mail from every key except its creator or a key scoped to that deal (`test_mnpi_docs.py`, `test_digest_mnpi.py`). Missing: MNPI check on exports (XLSX/DOCX/PPTX), outreach and agent answers, audit of who saw a walled deal, shared notes | UI |
| 17 | Firm memory / firm knowledge | BUILT (v1) | Cited profile of firm rules and preferences, extract from docs and emails | agent core |
| 18 | Agent + workflow orchestration | BUILT (v1) | Tool registry, workflow runner, bounded agent loop, run log | agent core |
| 19 | Source transparency | BUILT | Citations verified, source viewer, audit chain | - |
| 20 | Financial calculation toolkit | BUILT | LTM, net debt, NWC, IRR/TVPI/DPI, waterfall, share ledger | - |
| 21 | Due-diligence request tracking | BUILT | DD requests, summary, DDQ | - |
| 22 | Outreach emails at scale | DONE | Drafts from known fields (`POST /targets/outreach`). Review queue: `POST /targets/outreach/queue` drafts many targets; a senior key approves or rejects each; only an approved, unchanged draft sends, once, to the target's saved contacts (`POST /targets/{id}/contacts`) or addresses given. Daily send cap `OUTREACH_DAILY_LIMIT` (default 50, 429 past it). Agents, workflows and schedules cannot reach sending | integrations |

## 3. Firm knowledge: what the terms mean

"Firm knowledge" is the unwritten rulebook a firm runs on. It lives in LPAs, IC charters, policies, old memos and email. When a partner leaves it leaves too. The profile stores each rule as `key -> value`, plus the document, page and quote it came from, plus a review status. Agents read it so output follows house rules.

### Governance
- **board_meeting_frequency**: how often portfolio boards meet (quarterly, monthly). Drives reporting calendar.
- **ic_quorum**: partners needed for a valid IC vote.
- **partner_signoff_threshold**: deal size or risk level above which named partners must approve (for example EV above 50m needs managing partner).
- **investment_committee_cadence**: weekly or ad hoc IC schedule.
- **approval_matrix**: who approves what (follow-ons, write-downs, fees, add-ons).
- **conflict_policy**: related-party and cross-fund rules.
- **key_person_provisions**: LPA clauses that pause investing if named partners leave.
- **concentration_limit**: max share of fund in one company, sector or country.
- **leverage_limit**: max debt/EBITDA the firm will use.
- **esg_exclusions**: sectors never invested in.

### Deal process
- **deal_screening_criteria**: size, sector, geography, growth and margin floors that make a deal worth a look.
- **target_ev_range**, **target_ebitda_range**, **target_ownership**: sweet spot sizes and control stance.
- **return_hurdles**: required IRR and MOIC (for example 20% IRR, 2.5x).
- **hold_period**: expected years to exit.
- **pipeline_stages**: the firm's stage names (sourced, NDA, CIM, IOI, LOI, confirmatory, IC, signed).
- **dd_workstreams**: which DD areas the firm always runs (commercial, financial, legal, tax, ESG, IT).
- **preferred_advisors**: law firms, accountants, consultants and banks the firm reuses, by workstream.
- **ic_memo_template**: section order and length the firm expects.
- **red_flag_playbook**: clauses and metrics that trigger escalation (change-of-control, customer concentration over 20%).
- **valuation_methods**: DCF, comps, precedents, LBO weighting; default multiple (EV/EBITDA, EV/Revenue).
- **fee_terms**: management fee, carry, hurdle, catch-up (LPA).

### Portfolio and LP
- **kpi_reporting_cadence**: how often companies send KPIs (monthly, quarterly) and by when.
- **kpi_definitions**: firm definition of ARR, churn, adjusted EBITDA, so numbers compare.
- **covenant_monitoring**: tests and headroom thresholds that raise alerts.
- **valuation_policy**: how and when holdings are marked (IPEV, quarterly).
- **lp_reporting_tone**: formal or plain, conservative or upbeat, language rules.
- **lp_reporting_calendar**: quarterly letter, annual meeting, capital call notice lead time.
- **reporting_currency**: base currency and FX source.
- **value_creation_levers**: standard 100-day plan items.

### People and relationships
- **partner_sector_specialisations**: which partner leads which sector, so deals route correctly.
- **expert_network**: former executives and operating partners by sector.
- **lender_relationships**: preferred debt providers.
- **co_investors**: usual syndicate partners.
- **ceo_candidate_bench**: execs the firm would back.

### Data and systems
- **data_providers**: which sources the firm licenses (Cap IQ, FactSet, PitchBook, Preqin, Bloomberg, Refinitiv).
- **capiq_usage**: S&P Capital IQ is the S&P screening, comps and company-financials database, widely used for public comps and precedent deals. The profile records whether the firm has it and which screens or templates it uses; the data itself comes in through the Cap IQ connector (integrations thread).
- **crm_system**: DealCloud, Affinity, Salesforce.
- **document_system**: SharePoint, Box, Drive, Intralinks, Datasite.
- **naming_conventions**: deal code names, folder structure.
- **data_retention_policy**: how long deal files are kept (also a regulatory item).

Not every term appears in every firm. Missing keys stay empty; the agent asks rather than guesses.

## 4. Build order (this thread)
1. Firm-knowledge profile: term catalogue, cited extraction from documents and emails, review, API. (PR 2)
2. Agent core: tool registry, workflow runner, bounded agent loop, run log, firm profile in context. (PR 3)
3. Proactive layer: watchers (covenants, filings, KPIs, screening matches) write alerts to an inbox; email delivery via integrations; scheduler for workflows.
