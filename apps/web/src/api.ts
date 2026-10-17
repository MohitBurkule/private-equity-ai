export interface DocumentInfo { id: string; filename: string; n_pages: number; deal?: string | null }
export interface Hit { document_id: string; page: number; score: number; snippet: string }
export interface Claim { text: string; document_id: string; page: number; quote: string; reason?: string }
export interface AskResult { status: string; detail: string; claims: Claim[]; rejected: Claim[] }
export interface PageData { document_id: string; page: number; text: string; method?: string; ocr_confidence?: number | null }

let apiKey = sessionStorage.getItem("pe_api_key") ?? "";
export const setApiKey = (k: string) => { apiKey = k; sessionStorage.setItem("pe_api_key", k); };
export const getApiKey = () => apiKey;
const auth = (): HeadersInit => (apiKey ? { Authorization: `Bearer ${apiKey}` } : {});

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  documents: () => fetch("/api/documents", { headers: auth() }).then((r) => j<DocumentInfo[]>(r)),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/documents", { method: "POST", body: fd, headers: auth() }).then((r) => j<DocumentInfo>(r));
  },
  search: (q: string, docId?: string) =>
    fetch(`/api/search?q=${encodeURIComponent(q)}${docId ? `&doc_id=${docId}` : ""}`, { headers: auth() }).then((r) => j<Hit[]>(r)),
  page: (docId: string, n: number) => fetch(`/api/documents/${docId}/pages/${n}`, { headers: auth() }).then((r) => j<PageData>(r)),
  /** The page as filed, PNG, with the quote highlighted when the page contains it. */
  pageImage: (docId: string, n: number, quote: string) =>
    fetch(`/api/documents/${docId}/pages/${n}/image?quote=${encodeURIComponent(quote)}`, { headers: auth() }).then(async (r) => {
      if (!r.ok) throw new Error(`page image ${r.status}`);
      return { url: URL.createObjectURL(await r.blob()), highlighted: r.headers.get("X-Quote-Highlighted") === "1" };
    }),
  /** A filing page as filed (HTML), with the tagged figure for the quote marked and scrollable. */
  /** Target by quote, or by `anchor` (an element id) or `offset` (a character offset) when a citation names one. */
  pageHtml: (docId: string, n: number, quote: string, target: { anchor?: string; offset?: number } = {}) => {
    const params = new URLSearchParams({ quote });
    if (target.anchor) params.set("anchor", target.anchor);
    if (target.offset !== undefined) params.set("offset", String(target.offset));
    return fetch(`/api/documents/${docId}/pages/${n}/html?${params}`, { headers: auth() }).then(async (r) => {
      if (!r.ok) throw new Error(`page html ${r.status}`);
      return { html: await r.text(), highlighted: r.headers.get("X-Quote-Highlighted") === "1" };
    });
  },
  ask: (question: string, docId?: string) =>
    fetch("/api/ask", {
      method: "POST",
      headers: { ...auth(), "Content-Type": "application/json" },
      body: JSON.stringify({ question, doc_id: docId || null }),
    }).then((r) => j<AskResult>(r)),
  memo: (entity: string) =>
    fetch(`/api/memo?entity=${encodeURIComponent(entity)}`, { headers: auth() }).then((r) => j<{ markdown: string }>(r)),
};

export interface FactRow {
  id: number; entity: string; metric: string; period: string; value: string; unit: string; status: string;
  reviewed_by: string | null; sources: { document_id: string; page: number; quote: string }[];
}
export interface DealRow { name: string; stage: string; note: string | null; documents: number; dd_total: number; dd_open: number }
export interface DDRow { id: number; deal: string; category: string; title: string; status: string; document_id: string | null }
export interface DDQuestionRow {
  id: number; deal: string; request_id: number | null; question: string; status: "open" | "answered";
  answer: string | null; document_id: string | null; page: number | null; quote: string | null;
  asked_at: string; answered_at: string | null;
}
export interface LboTieRow {
  cell: string | null; value: string | null; reason: string | null; tie: "tied" | "untied" | "no_value";
  fact_ids: number[]; is_lbo_input: boolean;
}
export interface LboTiesOut { inputs: Record<string, LboTieRow>; untied: string[]; lbo_missing: string[] }
export interface ICDecisionRow { id: number; deal: string; outcome: string; rationale: string; dissent: string | null; dissenter: string | null; recorded_at: string }
export interface ICPrecedents { deal: string; stage: string | null; precedents: ICDecisionRow[]; outcome_counts: Record<string, number>; compared_deals: number }
export interface ICReview { deal: string; latest: ICDecisionRow | null; dissents: ICDecisionRow[]; changed_since_ic: { document_id: string; filename: string; created_at: string | null }[]; ic_recorded: boolean }
/** One key of a tenant with its deal wall. A null deals list means unrestricted. */
export interface KeyWall { key_id: string; role: string; revoked: boolean; deals: string[] | null; deal_roles: Record<string, string> }
export interface EvalRunRow { id: number; suite: string; ran_at: string; note: string | null; metrics: Record<string, unknown> }
/** Cited input: a verified fact id, as /lbo/returns requires. Multiples are inputs too, so they must be cited. */
export interface LboAssumption { value: string; set_by: string; set_on: string; reason: string }
export interface LboRequest {
  inputs: Record<string, { fact_id: number } | { derived: { formula: string; entity: string; period: string } } | { value: string; assumption: Omit<LboAssumption, "value"> }>;
  entry_multiples?: string[]; exit_multiples?: string[];
}
export interface FlagshipStep { step: string; status: "ok" | "skipped" | "failed"; reason: string; result: Record<string, unknown> }
export interface FlagshipResult { document_id: string; steps: FlagshipStep[] }
export interface FlagshipBody {
  document_id: string; entity: string; extract: boolean; sic?: string; cik?: string; peers_pages?: number;
  precedents?: { since: string; until: string; limit: number }; legal_doc_type?: "nda" | "spa" | "credit" | null;
  lbo: { inputs: Record<string, { value: string; assumption: string }> };
}

export interface LboRunRow {
  id: number; name: string; created_at: string; created_by: string;
  moic: string; irr: string | null; entry_ev: string; exit_equity: string;
}
export interface LboRunDetail extends LboRunRow { request: LboRequest; result: LboResult }

export interface LboResult {
  entry_ev: string; debt: string; fees: string; equity: string; exit_ev: string; exit_net_debt: string; exit_equity: string;
  moic: string; irr: string | null; dividends: string; sensitivity: [string, string, string | null, string | null][] | null;
  assumptions: { input: string; value: string; set_by: string; set_on: string; reason: string }[];
  derived: { input: string; formula: string; components: number[] }[];
}
export interface CovenantTest { period: string; status: string; value: string; threshold: string; unit?: string }
export interface CovenantStatus {
  covenants: { id: number; kpi_metric: string; operator: string; tests: CovenantTest[] }[];
  breaches: (CovenantTest & { covenant_id: number; kpi_metric: string })[];
}
/** A sourcing candidate from a live search. Not imported until someone adds it as a target. */
export interface SearchCandidate { name: string; source_url: string | null; form?: string; file_date?: string; already_imported?: boolean }
export interface SearchOut { total: number; items: SearchCandidate[] }
export interface AlertRow { id: number; kind: string; severity: string; title: string; detail: string; fact_ids: number[]; status: string; created_at: string }
export interface Breach { company: string; kpi_metric: string; period: string; status: string; value: string; threshold: string; unit?: string }
export interface ConflictSource { fact_id: number; value: string; documents: { document_id: string; filename: string | null; page: number; quote: string }[] }
export interface Conflict {
  entity: string; metric: string; period: string; basis: string; spread_pct: string; likely_rounding: boolean;
  severity: "rounding" | "minor" | "material"; cross_document: boolean; values: { value: string; fact_id: number }[];
  sources: ConflictSource[];
}
export type ConnectorState = "connected" | "needs_key" | "stubbed";
export type ConnectorHealth = "never_run" | "ok" | "error";
export interface Connector {
  name: string; label: string; category: string; auth: string; status: "live" | "planned"; state: ConnectorState; detail: string;
  health?: ConnectorHealth; last_run?: string | null; last_status?: string | null;
}
/** A computed figure with every input's citation. Withheld (ok false) names what is missing; never a guess. */
export interface QoeCalc {
  name: string; entity: string; ok: boolean; value: string | null; unit: string | null; formula: string;
  missing: string[]; problems: string[];
  inputs: { role: string; sign: number; fact_id: number; metric: string; period: string; value: string; unit: string;
    sources: { document_id: string; page: number; locator: string; quote: string }[] }[];
  one_off_flags?: { fact_id: number; amount: string; quote: string; locator: string }[];
}
export type NwcPeg = QoeCalc & { per_period: Record<string, QoeCalc> };
export interface TrendRow {
  period: string; revenue: string | null; growth_pct: string | null; ebitda_margin_pct: string | null; missing: string[];
}

export interface CompsOut {
  target: string; period: string;
  peers: { entity: string; multiples: Record<string, string | null> }[];
  stats: Record<string, { n: number; min: string | null; q1: string | null; median: string | null; q3: string | null; max: string | null }>;
  implied: { metric: string; multiple: string; low?: string | null; mid?: string | null; high?: string | null; unit?: string; note: string; target_value?: string }[];
}
export interface AgentRunOut {
  id: number; status: string; error: string | null;
  steps: { id?: string; tool: string; args?: unknown; output?: unknown; error?: string }[];
  result: (AskResult & { status: string }) | Record<string, unknown> | null;
}
export interface WorkflowInfo { name: string; description: string; inputs: Record<string, string>; steps: { id: string; tool: string }[] }
export interface FirmRow { id: number; key: string; value: string; status: string; source: { document_id: string; page: number; quote: string } }
export interface FirmOut { profile: Record<string, FirmRow[]>; coverage: { known: number; total: number; missing: string[] } }
export interface DDSummary { total: number; closed: number; pct_complete: number | null; by_category: Record<string, { open: number; received: number; waived: number }> }
export interface LegalOut { doc_type: string; absent: string[]; findings: { term: string; value: string; page: number; quote: string; needs_review: boolean; document_id: string }[] }
export interface Report {
  breaches: Breach[];
  companies: { id: number; name: string; kpis: { metric: string; period: string; value: string; unit: string; sources: { document_id: string; page: number }[] }[] }[];
}

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const r = await fetch(`/api${path}`, {
    method,
    headers: { ...auth(), ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return j<T>(r);
}

export type Target = {
  id: number; name: string; source: string; source_ref: string; source_url: string | null;
  sector: string | null; country: string | null; region: string | null; lat: string | null; lng: string | null;
  revenue: string | null; currency: string | null; revenue_period: string | null; revenue_url: string | null; status: string;
};
export interface ScreenBody {
  sectors?: string[]; countries?: string[]; min_revenue?: string; max_revenue?: string; weights?: Record<string, number>;
}
export interface ScreenOut {
  matches: number; review: number;
  applied: { sectors: string[]; countries: string[]; weights: Record<string, number>; weights_source: { key: string; value: string; quote: string } | null };
  items: (Target & { verdict: string; score: number | null; criteria: Record<string, string> })[];
}
export type TargetBenchmark = {
  sector: string | null; peers: number; excluded_no_revenue: number; median: string | null; q1: string | null; q3: string | null;
  target?: { id: number; name: string; revenue: string; percentile: number };
};
export type TargetFilter = { sector?: string; country?: string; min_revenue?: string; max_revenue?: string; q?: string };
export type Facets = { sector: { value: string | null; count: number }[]; country: { value: string | null; count: number }[]; total: number; revenue_unknown: number };

export interface AlertBrief { since: string; total: number; by_kind: Record<string, number>; by_severity: Record<string, number> }

export interface RefreshOut { checked: number; refreshed: number; failed: number; dissolved: number }

export interface Note { id: number; author: string; body: string; created_at: string; edited_at: string | null }

// Deal and target notes share one shape; only the path differs. The server decides who may edit (author, or a whole-tenant key).
export const notesFor = (base: string) => ({
  list: () => call<Note[]>(`${base}/notes`),
  add: (body: string) => call<Note>(`${base}/notes`, "POST", { body }),
  edit: (id: number, body: string) => call<Note>(`${base}/notes/${id}`, "PATCH", { body }),
});

export const dealNotes = (deal: string) => notesFor(`/deals/${encodeURIComponent(deal)}`);
export const targetNotes = (tid: number) => notesFor(`/targets/${tid}`);

export const api2 = {
  targets: (f: TargetFilter) => {
    const p = new URLSearchParams({ limit: "1000" });
    Object.entries(f).forEach(([k, v]) => v && p.set(k, v));
    return call<{ total: number; items: Target[] }>(`/targets?${p}`);
  },
  targetBenchmark: (targetId: number, sector: string) =>
    call<TargetBenchmark>(`/targets/benchmark?target_id=${targetId}&sector=${encodeURIComponent(sector)}`),
  targetFacets: () => call<Facets>("/targets/facets"),
  screen: (body: ScreenBody) => call<ScreenOut>("/targets/screen", "POST", body),
  refreshTargets: () => call<RefreshOut>("/targets/refresh", "POST"),
  facts: (status?: string) => call<FactRow[]>(`/facts${status ? `?status=${status}` : ""}`),
  review: (id: number, action: "accept" | "reject", note?: string) => call<FactRow>(`/facts/${id}/review`, "POST", { action, note }),
  deals: () => call<DealRow[]>("/deals"),
  createDeal: (name: string) => call<DealRow>("/deals", "POST", { name }),
  setStage: (name: string, stage: string) => call<DealRow>(`/deals/${encodeURIComponent(name)}`, "PATCH", { stage }),
  dd: (deal: string) => call<DDRow[]>(`/dd/requests?deal=${encodeURIComponent(deal)}`),
  ddSeed: (deal: string) => call<{ created: number }>("/dd/requests/seed", "POST", { deal }),
  ddStatus: (id: number, status: string) => call<DDRow>(`/dd/requests/${id}`, "PATCH", { status }),
  icPrecedents: (deal: string) => call<ICPrecedents>(`/ic/precedents?deal=${encodeURIComponent(deal)}`),
  icReview: (deal: string) => call<ICReview>(`/ic/review?deal=${encodeURIComponent(deal)}`),
  ddQuestions: (deal: string) => call<DDQuestionRow[]>(`/dd/questions?deal=${encodeURIComponent(deal)}`),
  ddQuestionAdd: (deal: string, question: string) => call<DDQuestionRow>("/dd/questions", "POST", { deal, question }),
  ddQuestionAnswer: (id: number, cite: { answer: string; document_id: string; page: number; quote: string }) =>
    call<DDQuestionRow>(`/dd/questions/${id}`, "PATCH", cite),
  report: () => call<Report>("/portfolio/report"),
  brief: (since: string) => call<AlertBrief>(`/alerts/brief?since=${encodeURIComponent(since)}`),
  connectors: () => call<Connector[]>("/connectors"),
  syncConnector: (name: string, token: string, deal: string) =>
    call<{ ingested: unknown[]; skipped?: unknown[] }>(`/connectors/${name}/sync`, "POST", { token, deal: deal || null, limit: 50 }),
  comps: (body: { target: string; peers: string[]; period: string; metrics: string[] }) => call<CompsOut>("/calc/comps", "POST", body),
  /** Named inputs of an LBO workbook, each tied to verified facts with the same concept and value. */
  /** Admin-only. The token is passed per call and never stored, so it dies with the page. */
  adminKeys: (tenantId: string, adminToken: string) =>
    fetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/keys`, { headers: { "X-Admin-Token": adminToken } })
      .then((r) => j<{ keys: KeyWall[] }>(r)).then((d) => d.keys),
  lboWorkbookTies: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/lbo/workbook/ties", { method: "POST", body: fd, headers: auth() }).then((r) => j<LboTiesOut>(r));
  },
  calcPeriods: (entity: string) => call<{ entity: string; periods: string[] }>(`/calc/periods?entity=${encodeURIComponent(entity)}`),
  qoeEbitda: (entity: string, period: string) =>
    call<QoeCalc>(`/calc/normalized-ebitda?entity=${encodeURIComponent(entity)}&period=${encodeURIComponent(period)}`),
  nwcPeg: (entity: string, periods: string) =>
    call<NwcPeg>(`/calc/nwc-peg?entity=${encodeURIComponent(entity)}&periods=${encodeURIComponent(periods)}`),
  revenueTrend: (entity: string, periods: string) =>
    call<{ entity: string; rows: TrendRow[] }>(`/calc/revenue-trend?entity=${encodeURIComponent(entity)}&periods=${encodeURIComponent(periods)}`),
  agent: (goal: string) => call<AgentRunOut>("/agent/run", "POST", { goal }),
  workflows: () => call<WorkflowInfo[]>("/agent/workflows"),
  runWorkflow: (name: string, inputs: Record<string, string>) => call<AgentRunOut>(`/agent/workflows/${name}/run`, "POST", { inputs }),
  firm: () => call<FirmOut>("/firm-knowledge?include_pending=true"),
  firmTerms: () => call<{ key: string; group: string; label: string; hint: string }[]>("/firm-knowledge/terms"),
  firmReview: (id: number, status: string) => call<unknown>(`/firm-knowledge/${id}/review`, "POST", { status }),
  ddSummary: (deal: string) => call<DDSummary>(`/dd/summary?deal=${encodeURIComponent(deal)}`),
  legalTerms: (docId: string, docType: string) => call<LegalOut>(`/documents/${docId}/legal-terms?doc_type=${docType}`),
  conflicts: () => call<Conflict[]>("/facts/conflicts"),
  evals: () => call<EvalRunRow[]>("/evals?limit=200"),
  alerts: (status?: string) => call<AlertRow[]>(`/alerts${status ? `?status=${status}` : ""}`),
  setAlertStatus: (id: number, status: string) => call<AlertRow>(`/alerts/${id}/status`, "POST", { status }),
  searchEdgar: (body: { query: string; forms: string[]; since: string; until: string; limit?: number }) =>
    call<SearchOut>("/targets/search/edgar", "POST", body),
  searchCompaniesHouse: (body: { query: string; limit?: number }) => call<SearchOut>("/targets/search/companies-house", "POST", body),
  lboReturns: (body: LboRequest) => call<LboResult>("/lbo/returns", "POST", body),
  flagship: (body: FlagshipBody) => call<FlagshipResult>("/flagship/run", "POST", body),
  // A plain link would not send the key, so the memo is fetched with it and saved from a blob.
  memoBlob: (entity: string) => fetch(`/api/memo.pptx?entity=${encodeURIComponent(entity)}`, { headers: auth() })
    .then((r) => { if (!r.ok) throw new Error(`memo: ${r.status}`); return r.blob(); }),
  lboRuns: () => call<LboRunRow[]>("/lbo/runs"),
  lboRun: (id: number) => call<LboRunDetail>(`/lbo/runs/${id}`),
  lboSave: (name: string, request: LboRequest) => call<LboRunRow>("/lbo/runs", "POST", { name, request }),
  covenants: (companyId: number) => call<CovenantStatus>(`/portfolio/companies/${companyId}/covenants`),
  emailReview: () => call<{ emails: UnattachedEmail[] }>("/email/review"),
  dealMeetings: (deal: string) => call<{ meetings: DealMeeting[] }>(`/deals/${encodeURIComponent(deal)}/meetings`),
  peerSets: (deal: string) => call<PeerSet[]>(`/deals/${encodeURIComponent(deal)}/peer-sets`),
  savePeerSet: (deal: string, targetId: number, name: string) => call<PeerSet>(`/deals/${encodeURIComponent(deal)}/peer-sets`, "POST", { target_id: targetId, name }),
  refreshPeerSet: (deal: string, id: number) => call<PeerSet>(`/deals/${encodeURIComponent(deal)}/peer-sets/${id}/refresh`, "POST"),
  people: (q: string, deal?: string) => {
    const p = new URLSearchParams({ q });
    if (deal) p.set("deal", deal);
    return call<{ query: string; people: PersonRow[] }>(`/people?${p}`);
  },
  addPerson: (body: PersonIn) => call<PersonRow>("/people", "POST", body),
  // A plain link would not send the key, so the research deck is fetched with it and saved from a blob.
  researchPptxBlob: (targetId: number) => fetch(`/api/targets/${targetId}/research.pptx`, { headers: auth() })
    .then((r) => { if (!r.ok) throw new Error(`research deck: ${r.status}`); return r.blob(); }),
  documentAccess: (tenantId: string, adminToken: string) => fetch(`/api/admin/tenants/${encodeURIComponent(tenantId)}/document-access`, {
    headers: { "X-Admin-Token": adminToken },
  }).then((r) => j<DocumentAccess>(r)),
  budgetVsActual: (companyId: number, period: string) => call<BudgetVsActual>(`/portfolio/companies/${companyId}/budget-vs-actual?period=${encodeURIComponent(period)}`),
  portfolioSubmissions: (period: string) => call<SubmissionsOut>(`/portfolio/submissions?period=${encodeURIComponent(period)}`),
  emailAttach: (docId: string, deal: string) => call<{ document_id: string; deal: string }>(`/email/review/${encodeURIComponent(docId)}/attach`, "POST", { deal }),
};

export interface UnattachedEmail { document_id: string; filename: string; source_url: string | null }

export interface DealMeeting { title: string; starts_at: string; url: string | null; board: string | null; source: string }

export interface PeerItem { cik: string; name: string; revenue?: string; [key: string]: unknown }
export interface PeerDropped { cik: string; name: string; reason: string }
export interface PeerSet { id: number; deal: string; name: string; target_id: number; items: PeerItem[]; dropped: PeerDropped[]; refreshed_at: string | null }

export interface PersonRow { id: number; name: string; organisation: string | null; title: string | null; expertise: string[]; deal: string | null; recorded_at: string }
export interface PersonIn { name: string; organisation?: string; title?: string; expertise?: string[]; deal?: string }

export interface DocumentAccessRow { document_id: string; filename: string; deal: string | null; connector: string; grants: string[] }
export interface DocumentAccess { documents: DocumentAccessRow[]; restricted: number }

/** A figure as the portfolio routes return it: its fact, and the document it was read from. */
export interface CitedFigure { value: string; fact_id: number; source: string; url: string | null }
export interface BudgetMetric { metric: string; unit: string; actual: CitedFigure | null; budget: CitedFigure | null; variance: string | null; variance_pct: string | null }
export interface BudgetVsActual { period: string; metrics: BudgetMetric[] }
export interface SubmissionRow { company_id: number; name: string; metrics: string[] }
export interface SubmissionsOut { period: string; submitted: SubmissionRow[]; missing: SubmissionRow[]; pct_submitted: number | null }

export const STAGES = ["sourcing", "screening", "dd", "ic", "signed", "closed", "passed"];
