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
- **Parsing**: Docling / Unstructured / LlamaParse / Azure Document Intelligence / Textract. Default Docling (permissive). **No AGPL or restricted-licence parsers in core**: PyMuPDF is AGPL; Marker/Surya code is Apache-2.0 but their model weights carry commercial-use limits (Open RAIL-M, revenue cap); MinerU has extra terms; OpenBB licence is ambiguous. These are optional adapters behind a licence tag, separately deployed, pending legal review. pdf.js for viewer. Pluggable cloud OCR for hard scans; benchmark on sample data.
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
Repo name; deployment target (cloud/on-prem); which vendor licences user holds (FactSet/PitchBook); target doc types; open-source licence (Apache-2.0 suggested).

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
- Retrieval (BM25 + finance synonym expansion, scoped to the gold document), 14 FinanceBench open-source questions on 10 sample filings: recall@1 0.14, @3 0.36, @5 0.50, @10 0.57 (`evals/run_retrieval_eval.py`). Without synonym expansion: @10 0.29. Small n and synonyms were tuned on these questions, so treat as an upper-biased baseline. Next steps: dense embeddings + cross-encoder rerank, statement-page classifier, and a held-out question set.

## 14. Excel ingest (implemented)
Workbooks ingest as one page per sheet; each cell is a line `Sheet!B7: value [=formula]` so quotes and citations address cells and formulas stay visible next to cached values. Hidden sheets are flagged in the text. Upload dispatch is by content (PDF or zip magic), not extension. Not yet done: external links, number formats, date system, very-hidden detection beyond sheet_state, header-path grids (research/06 s18).

## 15. Negative result: char-trigram hybrid
BM25 + char-trigram TF-IDF fused by RRF (`app/hybrid.py`) scored recall@10 0.50 vs 0.57 for BM25 alone on the 14 sample questions (n is tiny; difference is noise, but there is no gain), so `/search` stays on BM25. The `Ranker` protocol and RRF are kept as the plug-in point for dense embeddings and a cross-encoder reranker. Dense models could not be evaluated here: Hugging Face is blocked from the build sandbox. Needs a run with model access (suggested first candidates: bge-m3 or e5-large via fastembed/sentence-transformers, and an API embedding for comparison) on the larger golden sets.

## 16. Tenancy (implemented, app layer)
API keys map to a tenant (only the SHA-256 of a key is stored; keys are shown once). The tenant is taken only from the key, never from request fields. `tenant_id` is on document, fact, portfolio_company, kpi_observation and audit_event; pages and fact sources inherit through their parent. Document ids are `sha256(tenant_id:content_sha)`, so identical files in two tenants do not collide or reveal each other. Cross-tenant reads return the same 404 as missing objects; search filters by tenant before ranking; facts, memos, observations and audit chains are tenant scoped. Tests in `tests/test_tenancy.py` attack each path from a second tenant. `ADMIN_TOKEN` (env) enables `POST /admin/tenants`; unset means the endpoint always refuses.
Not done yet: Postgres row-level security as the second layer (FORCE ROW LEVEL SECURITY, non-owner app role, `SET LOCAL` tenant per transaction; research/09), key rotation and revocation, user identities and roles (OIDC), deal-level ACLs and ethical walls, rate limits.

## 17. XBRL cross-check (implemented)
`app/xbrl.py` loads SEC companyfacts and confirms a figure by concept, period, accession and unit. Results: `match`, `restated` (the claimed value matches one filing vintage but vintages disagree; all distinct values and filings are returned, nothing is picked silently), `mismatch`, `not_found`. Duplicate reports of the same value across filings are not conflicts. `GET /xbrl/check` wraps it with an injectable EDGAR client (`SEC_USER_AGENT` required, about 8 req/s); fetch failures return 502, never a guess. Eval on `golden_xbrl_v1`: 117 of 117 values equal the companyfacts value for the same accession, concept and period (`evals/run_xbrl_eval.py`). Caveat: period for 103 items came from dates in the question text because their inline-XBRL context ids are opaque, so this checks the lookup and values, not period parsing from raw filings. Live EDGAR fetching is untested here (sec.gov blocked in the build sandbox).
