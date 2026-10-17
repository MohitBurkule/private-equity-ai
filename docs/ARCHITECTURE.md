# PE Platform Architecture (v0.1 draft)

Status: v0.2. Revised with research round 1 (research/00-INDEX.md) and sample-data notes (data/NOTES.md). Research items tagged unverified there stay unverified here.

## 1. Principles
1. **Every number carries provenance.** No claim exists without a pointer to source doc + page + bbox/cell + extraction run. Unsourced output is rejected by the system, not by the reviewer.
2. **Extract deterministically, reason probabilistically.** Numbers come from structured extraction with validation (sums, cross-foots, units). LLM never "recalls" a figure; it quotes retrieved spans.
3. **Verify before display.** A separate verifier checks every generated claim against its cited span (NLI + numeric match). Fails -> flagged or dropped.
4. **Human in loop for IC output.** Drafts only; analyst approves; full audit log.
5. **Tenant isolation.** Deal rooms hold confidential/MNPI data. Row-level security, per-deal ACL, ethical walls, no cross-tenant training.
6. **Provider-agnostic.** LLM, embedding, data vendor behind interfaces.

## 2. Modules
| Module | Job |
|---|---|
| ingest | Upload/connectors (SharePoint, Drive, email, VDR dumps: Intralinks, Datasite). Dedupe by hash, virus scan, OCR, versioning. |
| parse | PDF/XLSX/DOCX/PPTX -> layout-aware blocks + tables (Docling/Unstructured; OCR fallback Tesseract/cloud). Keeps page, bbox, sheet, cell. |
| extract | Schema-driven extraction (financials, KPIs, covenants, cap table, legal terms). Pydantic schemas, LLM + validators, confidence. |
| index | Chunk (structure-aware), embed, store in pgvector/Qdrant; BM25 in Elasticsearch/OpenSearch. |
| retrieve | Hybrid (BM25+dense) + rerank (cross-encoder), metadata filters (deal, doc type, date, ACL applied pre-retrieval). |
| agents | Due-diligence workflows (QoE, commercial, legal red-flags, mgmt Q&A), IC memo generator, enterprise Q&A. Orchestrated by LangGraph; LlamaIndex for ingestion/retrieval. |
| verify | Claim-to-evidence checker, numeric reconciler, contradiction detector across docs. |
| market-data | Adapters: FactSet, PitchBook, free (SEC EDGAR, Companies House, Crunchbase-free, Yahoo/OpenBB), secondary platforms (Seedrs, Crowdcube, scraped only if ToS allows; otherwise manual import). |
| portfolio | Portfolio company tracking: KPI time series, covenant monitoring, valuation marks, alerts. |
| reports | IC memo/deck export (DOCX/PPTX) with footnoted citations linking back to viewer. |
| api | FastAPI, REST + SSE streaming, OIDC auth. |
| web | React+TS: doc viewer with highlight-on-citation, chat, deal workspace, review queue. |
| ops | Celery/Arq workers, Redis, Postgres, object store (S3/MinIO), OpenTelemetry, Langfuse. |

## 3. Data model (Postgres)
- `tenant`, `user`, `deal`, `deal_member` (ACL), `ethical_wall`.
- `document(id, deal_id, sha256, filename, mime, version, source, uploaded_by, status)`.
- `page(document_id, n, image_ref, text)`; `block(id, document_id, page, type, bbox, text, table_json, parse_run_id)`.
- `chunk(id, block_ids[], text, embedding, tsv)`.
- `fact(id, deal_id, entity_id, metric, period, value, unit, currency, scale, basis(GAAP/adj), extraction_run_id, confidence, status(auto/verified/rejected))`.
- `fact_source(fact_id, block_id, quote, cell_ref)` -- **mandatory, FK not null**.
- `entity(id, name, aliases, identifiers[LEI, CRN, CIK])` with resolution table.
- `claim(id, output_id, text)`, `claim_evidence(claim_id, fact_id|block_id, verdict, score)`.
- `output(id, kind[memo,answer,table], model, prompt_version, created_by)`.
- `run` tables (parse/extract/llm) store model, version, params, cost for reproducibility.
- `audit_log` append-only.

## 4. Citation-to-source design
1. Parser emits blocks with stable IDs + bbox. IDs never change within a doc version.
2. Generation prompt provides numbered evidence blocks; model must output JSON `{claim, evidence_ids[], quote}` per claim (structured output), not free prose.
3. Verifier: (a) quote is substring of block text (fuzzy, normalized); (b) numbers in claim match numbers in quote after unit/scale normalization; (c) NLI entailment for qualitative claims.
4. Renderer turns evidence_ids into links `/doc/{id}?page=n&block=b` highlighting bbox. Exports carry footnotes with doc name, page.
5. Anything failing check shown as "unverified" and excluded from exports by default.
6. Derived numbers (EBITDA margin) are computed in code from cited facts; formula + inputs shown.

## 5. Failure modes and mitigations
| Failure | Mitigation |
|---|---|
| OCR/table misparse (merged cells, multi-page tables, rotated scans) | Layout model + table-structure model; render-and-compare; cross-foot totals; low-confidence -> review queue |
| Units/scale errors ($000 vs $m, FY vs LTM, currency) | Explicit unit/scale/period fields; sanity ranges; reject mixed units |
| Adjusted vs reported metrics confusion | `basis` field; require definition citation |
| Hallucinated numbers/citations | Structured output + verifier; no verifier pass = no export |
| Stale/superseded docs (v3 vs v5 model) | Versioning, supersedes links, recency in rank, warn on conflicts |
| Conflicting figures across docs | Contradiction detector; surface both with sources |
| Entity ambiguity (same names, subsidiaries) | Entity resolution with identifiers; ask user on ambiguity |
| Retrieval miss on tables/numbers | Hybrid search, table-as-row chunks with headers, query rewriting, eval on recall |
| Prompt injection in uploaded docs | Treat doc text as data; delimiters; no tool actions from doc content; output filter |
| Data leakage across deals/tenants | RLS, ACL filter before retrieval, per-tenant index namespaces, test suite |
| Vendor API limits/licence (FactSet/PitchBook redistribution) | Cache per licence, store provenance + as-of date, adapter interface; free-source fallback |
| Scraping ToS (Seedrs/Crowdcube) | Prefer official/partner data or manual import; legal review before scraping |
| Model drift / provider outage | Pin versions, fallback chain, regression eval before upgrade |
| Cost blowups | Cache by (doc hash, schema version), batch, small models for triage |
| Large files (10k-page VDR) | Async pipeline, per-page idempotent tasks, progress, resumability |
| Password-protected/corrupt files | Detect, flag, request password; never silently skip |
| Non-English docs | Multilingual embeddings; flag translation, cite original |
| Regulatory (MNPI, GDPR, SOC2) | Encryption, audit, retention policies, EU region option, self-host/open-model path |
| Stale live data | Show as-of timestamp always |

## 6. Alternatives considered
- **Vector DB**: pgvector (chosen v1, one DB, RLS-compatible) vs Qdrant/Weaviate (scale, filtering) vs Elasticsearch dense. Interface-wrapped to swap.
- **Lexical search**: Elasticsearch vs OpenSearch (licence) vs Postgres FTS. Start Postgres FTS + OpenSearch optional; hybrid needed for exact numbers/names.
- **Parsing**: Docling / Unstructured / LlamaParse / Azure Document Intelligence / Textract. Default Docling (permissive). **Licence: the repo is AGPL-3.0, so AGPL dependencies (PyMuPDF, OpenBB) are allowed in core when they help. Still avoid parsers with commercial-use or revenue-cap limits.** PyMuPDF is AGPL (fine now); Marker/Surya code is Apache-2.0 but their model weights carry commercial-use limits (Open RAIL-M, revenue cap); MinerU has extra terms; OpenBB licence is ambiguous. These are optional adapters behind a licence tag, separately deployed, pending legal review. pdf.js for viewer. Pluggable cloud OCR for hard scans; benchmark on sample data.
- **Orchestration**: LangGraph (chosen for stateful agents) vs LlamaIndex Workflows vs custom. LlamaIndex used for ingestion/retrieval only; avoid framework lock-in via thin adapters.
- **LLMs**: Claude/GPT for reasoning; open models (Llama, Qwen, Mistral) via vLLM for on-prem tenants. Eval-driven selection.
- **Embeddings**: OpenAI, Voyage, BGE/E5 (open). Finance-tuned evaluated.
- **Queue**: Celery vs Arq vs Temporal (durable workflows; consider v2).
- **Long-context stuffing vs RAG**: RAG needed for citation, cost, ACL; long context used for single-doc deep reads.
- **Graph RAG**: considered for entity/relationship queries; defer until eval shows need.

## 7. Evaluation (build first)
- Gold set: sample CIMs, 10-K/annual reports, financial models with hand-labelled facts.
- Metrics: extraction exact-match by field, citation precision/recall, retrieval recall@k, answer faithfulness, numeric accuracy (target 99%+ with verified flag), latency, cost.
- CI regression on gold set; every prompt/model change must pass.

## 8. Deployment
Docker Compose (dev), Helm/K8s (prod). Services: api, worker, web, postgres, redis, minio, opensearch(optional), vllm(optional). Observability: OpenTelemetry + Langfuse. Secrets via env/Vault. CI: GitHub Actions (lint, mypy, pytest, eval, image build).

## 9. Repo layout (proposed)
```
apps/api (FastAPI)  apps/web (React/TS)  packages/{ingest,parse,extract,retrieve,agents,verify,connectors}
evals/  data/samples/  infra/{docker,helm}  docs/
```

## 10. Roadmap
M0 scaffold+CI+auth+RLS. M1 ingest/parse/citation viewer. M2 extraction+verifier+eval harness. M3 hybrid RAG chat with citations. M4 DD workflows + IC memo export. M5 market-data adapters + portfolio tracking. M6 secondary marketplaces, hardening, security review, open-source prep (licence, secrets scrub, docs).

## 11. Open questions
Repo name; deployment target (cloud/on-prem); which vendor licences user holds (FactSet/PitchBook); target doc types; open-source licence (decided: AGPL-3.0).

## 12. Revisions from research round 1
1. **Scope before retrieval.** Retrieval inside the filing is the bottleneck. Resolve company, period, doc type from metadata first, then search within that scope. `retrieve` takes a mandatory scope object; unscoped search is an explicit fallback.
2. **Numbers are code-checked, never LLM-judged.** `verify` compares claimed numbers to structured sources (XBRL companyfacts for filings, table cells for PDFs/Excel) with deterministic code. LLM judges only qualitative entailment.
3. **Span-level citations.** Evidence = doc id, PDF page (1-based), printed page label, bbox/line, table id + row label + column period. Code verifies the cited span contains the claimed value. A valid link alone is not enough.
4. **Abstention is first-class.** Answers may be "not found". Eval reports wrong-answer rate separately from abstention rate.
5. **Table extraction rules from hand tests (data/NOTES.md):** unit+scale bound per table (not per row); keep raw string and sign convention (parentheses = outflow) plus normalized value; column-to-period binding from header row; strip inline footnote numbers from row labels; same label in several statements needs statement-type disambiguation (e.g. MD&A vs cash-flow capex); `basis` tag GAAP/non-GAAP (earnings releases redefine items); narrative questions need paragraph-span citations, not cells.
6. **Page indexing:** source datasets (FinanceBench) are 0-indexed; store 1-based PDF page everywhere, convert at import.
7. **Restatements:** same company, multiple vintages; facts carry `as_reported_in` document and `restated_by` link. Test pair: 3M 2018 vs 2019 10-K.
8. **Eval data licensing:** FinanceBench is non-commercial, internal eval only, never shipped in the open-source repo. Build a PE golden set (CIMs, QoE, Excel models) since no public benchmark covers them; needs user-supplied documents.
9. **Secondary markets (Seedrs/Crowdcube):** no official API found. Ingest user-uploaded exports; no scrapers.
10. **Permissions-aware retrieval, ethical walls, audit trail from M0** (already in section 5; now a hard M0 gate).
11. **Untested:** OCR path (all 10 sample docs have text layers), restatement handling, XBRL cross-check. Blocked on network allowlist for sec.gov, data.sec.gov, Companies House.

## 13. Measured baselines
- **Retrieval, 14 FinanceBench questions (first run, n tiny):** BM25 recall@1/3/5/10 0.14/0.29/0.50/0.57; hybrid (BM25+trigram) 0.14/0.43/0.43/0.50; dense bge-small 0.29/0.43/0.50/0.57; hybrid+dense 0.21/0.43/0.57/0.71; hybrid+dense+rerank 0.14/0.36/0.43/0.71.
- **Answer accuracy, Gemma-2B, 12 numeric FinanceBench questions** (the subset of the first 50 gold rows with a numeric answer; top-2 pages; 160 output tokens): exact numeric match 1/12 (0.08; Wilson 95% CI about 0.00 to 0.29), abstained 7/12, model output unparseable 4/12, verified-wrong 0/12. Abstain when not correct 7/11. The 2B model is weak here; this is not a measure of the 9B model.
- **Answer accuracy, Gemma-2-9B (Q4_K_M), same 12 questions, same settings:** exact numeric match 0/12, verified-wrong 1/12, abstained 11/12, errors 0/12. Abstain when not correct 11/12. Both models stay weak on this set; the 9B model abstains more and is wrong in one case where the verifier let a claim through. Run in checkpointed chunks on CPU, about 2 to 4 minutes per question.
- **Answer accuracy, Gemma-2-9B, k=5 pages (same 12 questions):** exact numeric 0/12, verified-wrong 1/12, abstained 8/12, errors 3/12. k=5 needs an 8192-token context (4096 overflows). Each question takes about 10 minutes on CPU, mostly prefill.
- **Retrieval recall, all 150 gold rows, doc-scoped (gold page = evidence_page_num + 1):** BM25 @1 0.193, @5 0.473, @10 0.627; BM25 + char-trigram RRF @1 0.147, @5 0.380, @10 0.500. Char-trigram fusion hurts, so the default drops it when dense is on (PR #476).
- **Retrieval recall, 24-row subset (first 8 docs), dense:** dense alone @1 0.208, @5 0.542, @10 0.583; BM25 + dense RRF @1 0.125, @5 0.458, @10 0.625; BM25 + trigram + dense @1 0.125, @5 0.292, @10 0.417. Small sample; a full dense run over all docs did not finish on this box.
- **Answer diagnostics, 9B at k=5 (raw logs, `--ids` rerun):** 03029, 04672 and 06655 returned an empty claim list, so the model abstained with the gold page in context (BM25 top-5 proxy). 01319 returned two claims citing page 181 that the verifier rejected. The earlier 3 "error" rows were the 256-token cap truncating JSON; at 512 tokens 01319 no longer errors. Gold-in-context abstains point to the prompt or the model, not the verifier. Not rerun: 04417, 05718, 08286, 04254 at k=5.
- **Box limit (k=5 setup):** on this CPU a 9B k=5 question takes 10 to 15 minutes, and a trimmed 2500-char run did not finish its first question in two 9-minute calls. The k=5 numbers are therefore partial. Follow-up: 9B k=5 on a GPU or a larger machine (listed in `evals/golden/README.md`). Do not compare k=5 with k=2 rows.
- **Not yet run:** the full 150-row dense comparison, and the citation-trace eval over all 12 questions (checkpointed; run with `--n 1` per call).
- Retrieval (BM25 + finance synonym expansion, scoped to the gold document), 14 FinanceBench open-source questions on 10 sample filings: recall@1 0.14, @3 0.36, @5 0.50, @10 0.57 (`evals/run_retrieval_eval.py`). Without synonym expansion: @10 0.29. Small n and synonyms were tuned on these questions, so treat as an upper-biased baseline. Next steps: dense embeddings + cross-encoder rerank, statement-page classifier, and a held-out question set.

## 14. Excel ingest (implemented)
Workbooks ingest as one page per sheet; each cell is a line `Sheet!B7: value [=formula]` so quotes and citations address cells and formulas stay visible next to cached values. Hidden sheets are flagged in the text. Upload dispatch is by content (PDF or zip magic), not extension. Not yet done: external links, number formats, date system, very-hidden detection beyond sheet_state, header-path grids (research/06 s18).

## 15. Negative result: char-trigram hybrid
BM25 + char-trigram TF-IDF fused by RRF (`app/hybrid.py`) scored recall@10 0.50 vs 0.57 for BM25 alone on the 14 sample questions. Later, with dense embeddings added (section 13), hybrid+dense reached recall@10 0.71, so the product retriever is now hybrid+dense (`default_index`). The `Ranker` protocol and RRF are kept as the plug-in point for dense embeddings and a cross-encoder reranker. Dense models could not be evaluated here: Hugging Face is blocked from the build sandbox. Needs a run with model access (suggested first candidates: bge-m3 or e5-large via fastembed/sentence-transformers, and an API embedding for comparison) on the larger golden sets.

## 16. Tenancy (implemented, app layer)
API keys map to a tenant (only the SHA-256 of a key is stored; keys are shown once). The tenant is taken only from the key, never from request fields. `tenant_id` is on document, fact, portfolio_company, kpi_observation and audit_event; pages and fact sources inherit through their parent. Document ids are `sha256(tenant_id:content_sha)`, so identical files in two tenants do not collide or reveal each other. Cross-tenant reads return the same 404 as missing objects; search filters by tenant before ranking; facts, memos, observations and audit chains are tenant scoped. Tests in `tests/test_tenancy.py` attack each path from a second tenant. `ADMIN_TOKEN` (env) enables `POST /admin/tenants`; unset means the endpoint always refuses.
Not done yet: Postgres row-level security as the second layer (FORCE ROW LEVEL SECURITY, non-owner app role, `SET LOCAL` tenant per transaction; research/09), key rotation and revocation, user identities and roles (OIDC), deal-level ACLs and ethical walls, rate limits.

## 17. XBRL cross-check (implemented)
`app/xbrl.py` loads SEC companyfacts and confirms a figure by concept, period, accession and unit. Results: `match`, `restated` (the claimed value matches one filing vintage but vintages disagree; all distinct values and filings are returned, nothing is picked silently), `mismatch`, `not_found`. Duplicate reports of the same value across filings are not conflicts. `GET /xbrl/check` wraps it with an injectable EDGAR client (`SEC_USER_AGENT` required, about 8 req/s); fetch failures return 502, never a guess. Eval on `golden_xbrl_v1`: 117 of 117 values equal the companyfacts value for the same accession, concept and period (`evals/run_xbrl_eval.py`). Caveat: period for 103 items came from dates in the question text because their inline-XBRL context ids are opaque, so this checks the lookup and values, not period parsing from raw filings. Live EDGAR fetching is untested here (sec.gov blocked in the build sandbox).

## 18. Cited answers (implemented, model untested)
`POST /ask` retrieves tenant-scoped pages, passes them to the model as delimited untrusted data, and accepts only JSON claims `{text, doc_id, page, quote}`. Code verifies each claim: the document belongs to the tenant, the quote appears on the cited page, and every non-year number in the claim equals a number in the quote (sign ignored, so `1,577` matches `(1,577)`; unit-converted figures such as "$1.58 billion" are rejected, conservatively). Unverified claims are never shown as answers; if none verify the response is `not_found` and the rejected claims are returned with reasons. URLs and images are stripped from claim text. Unusable model output returns `error`. Tests use a fake model, covering wrong numbers, fabricated quotes, cross-tenant citation, injection text in a document, junk output and abstention. Not measured: how often a real model produces verifiable claims (needs an API key and the golden sets), and semantic entailment (the quote supports the claim's meaning) is not checked yet. Provider is chosen with `LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` + `ANTHROPIC_MODEL`; the Anthropic adapter itself has not been run here.

## 19. UK iXBRL accounts (implemented)
`app/ixbrl.py` reads Companies House inline XBRL (prefix-agnostic tags, zero-dash, scale, sign, non-dimensional contexts only, latest balance-sheet instant) and recomputes two identities: fixed assets + net current assets = total assets less current liabilities, and net assets = equity. A failing identity makes the filing unreliable; `POST /documents` accepts iXBRL HTML (detected by content) and puts `[UNRELIABLE: ...]` at the top of the page text so the warning travels with every quote. Eval on `golden_uk_ixbrl_v1` (45 filings, 11 failing their own arithmetic): reliability flag, identity checks and the headline figures agree on 45 of 45 (`evals/run_uk_eval.py`). Caveat: the golden labels were produced by the data thread's own parser using the same identities, so this shows agreement between two implementations, not independent ground truth; a human read of the 11 flagged filings against the rendered accounts is still owed. Not covered: P&L and notes, audited vs unaudited vs micro-entity differences, group accounts, filings that are scanned PDFs (the OCR path is still untested in the app).

## 20. OCR (implemented, optional)
`pip install '.[ocr]'` and `OCR_ENABLED=1` run rapidocr-onnxruntime (via pypdfium2 rendering) on pages with fewer than 20 characters of text layer. Boxes are grouped into lines by vertical centre; pages are stored with `method=ocr` and a mean confidence, shown in the UI with a warning. Facts quoted from an OCR page get status `ocr_unverified` and are excluded from memos until a person confirms them. Without the OCR extra, such pages stay empty and a warning is logged. Tested on the one scanned Companies House notice in the sample data (single page, text recognised with confidence about 0.8). Not tested: dense financial tables in scans, rotated or skewed pages, multi-page scans, speed at data-room scale (about 1.6 s per page here), non-English text. Schema changes now go through Alembic (see section 21).

## 21. Migrations (implemented)
Postgres schema is managed by Alembic (`apps/api/alembic`, baseline revision `0001`), run at API startup as the owner role (`MIGRATE_DATABASE_URL`) before RLS policies are (re)applied. SQLite (dev/tests) uses `create_all`. A Postgres test builds the schema through migrations in an isolated schema and fails if the models drift from them (no unmigrated model change can merge), and checks a second run is a no-op. Create a revision with `cd apps/api && MIGRATE_DATABASE_URL=... alembic revision --autogenerate -m "..."`. Not done: downgrade paths are autogenerated and untested; data migrations; zero-downtime guidance.

## 22. Secondary-market data (Seedrs/Republic Europe, Crowdcube) and hardening
Research found no official API for either platform and an explicit scraping ban in Republic Europe's terms, so the platform does not scrape. Supported route: the investor downloads their own account export (CSV) and uploads it; rows are stored as citable lines (`row N: Column=value | ...`). Real export layouts have not been seen yet, so there is deliberately no column-specific parser; add one per platform once sample exports exist. Licensed feeds can plug in later through the same document model. Also added: key rotation and revocation (`api_key.revoked`, migration 0002), per-tenant rate limit (429 with Retry-After), upload size cap (413).
