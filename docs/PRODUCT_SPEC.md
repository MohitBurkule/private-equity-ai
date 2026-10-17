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
| 1 | Sourcing and screening of targets | PARTIAL | Deals + stages, UK CH/PSC feeds, PitchBook/Crowdcube/Seedrs export import, holdings. Missing: criteria-driven screen over a universe, scoring, saved screens | workflows |
| 2 | Add-on search | MISSING | Needs entity universe + similarity + exclusion of owned/seen companies; uses firm screening criteria | workflows |
| 3 | Enterprise search (docs, email, data) | PARTIAL | Scoped BM25, hybrid plumbing (not wired), ACL, eml/office/xlsx/pdf parse, source viewer. Missing: dense retrieval + rerank, cross-deal "have we seen this", connectors | PDF + integrations |
| 4 | IC materials | PARTIAL | Cited memo, DOCX + PPTX export, facts gate. Missing: firm templates, version diff, comments, auto-pull from CRM/SharePoint | workflows |
| 5 | Trading comps | PARTIAL | `/market/quote` (Yahoo, Stooq, FactSet providers), XBRL companyfacts. Missing: comps table builder, implied range | comps |
| 6 | Precedent transactions | MISSING | Holdings import has deal rows; needs multiple calc + dataset | comps |
| 7 | Legal review (NDA, SPA, covenants) | PARTIAL | Covenants table, extract schemas, cap table, share ledger, waterfall. Missing: clause library, playbook compare, red-flag table | workflows |
| 8 | Portfolio tracking | BUILT (core) | Companies, KPI observations, covenants, change report, DOCX report, fund metrics, cohorts | - |
| 9 | Scheduled workflows and proactive alerts (inbox, email) | PARTIAL | Alert inbox + covenant watcher (`/alerts`), workflow runs (`/agent`). Email digest (`/alerts/digest`, SMTP) and periodic scan (`ALERT_SCAN_INTERVAL_S`) built. Watchers: covenants, stalled deals, overdue DD, firm leverage limit (accepted `leverage_limit` rule vs portfolio `net_leverage_x`). Missing: filing, KPI, screening watchers; per-user recipients | agent core |
| 10 | Document generation (decks, research, outreach emails) | PARTIAL | memo DOCX/PPTX, portfolio DOCX. Missing: outreach email batch, research report | workflows |
| 11 | Interactive dashboards | PARTIAL | React app, KPI panels. Missing: filterable target map, quarterly KPI board | UI |
| 12 | Integrations (FactSet, PitchBook, DealCloud, SharePoint, Outlook, Gmail, Drive, LinkedIn, Cap IQ) | PARTIAL | FactSet quote, PitchBook export, Yahoo/Stooq, SEC, CH. Missing: OAuth connectors, DealCloud, SharePoint, Outlook, Drive | integrations |
| 13 | PDF processing | PARTIAL | pdf text, OCR fallback, statement rows, SH01, iXBRL. Missing: layout/table models, chart reading | PDF |
| 14 | Data-conflict flags | BUILT (core) | `/facts/conflicts`, tie-out, sumcheck. Missing: CIM vs DD report vs annual report doc-level pairing UI | workflows |
| 15 | Benchmarking vs live data | PARTIAL | XBRL cross-check, quotes. Missing: peer sets, sector benchmark tables | comps |
| 16 | Workspaces (multi-deal, team) | PARTIAL | Deals, API-key roles, per-deal ACL. Missing: user identities/SSO, shared notes | UI |
| 17 | Firm memory / firm knowledge | BUILT (v1) | Cited profile of firm rules and preferences, extract from docs and emails | agent core |
| 18 | Agent + workflow orchestration | BUILT (v1) | Tool registry, workflow runner, bounded agent loop, run log | agent core |
| 19 | Source transparency | BUILT | Citations verified, source viewer, audit chain | - |
| 20 | Financial calculation toolkit | BUILT | LTM, net debt, NWC, IRR/TVPI/DPI, waterfall, share ledger | - |
| 21 | Due-diligence request tracking | BUILT | DD requests, summary, DDQ | - |
| 22 | Outreach emails at scale | MISSING | Needs mail connector (draft only, human sends) | integrations |

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
