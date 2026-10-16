export interface DocumentInfo { id: string; filename: string; n_pages: number }
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
export interface EvalRunRow { id: number; suite: string; ran_at: string; note: string | null; metrics: Record<string, unknown> }
export interface Breach { company: string; kpi_metric: string; period: string; status: string; value: string; threshold: string }
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

export const api2 = {
  facts: (status?: string) => call<FactRow[]>(`/facts${status ? `?status=${status}` : ""}`),
  review: (id: number, action: "accept" | "reject", note?: string) => call<FactRow>(`/facts/${id}/review`, "POST", { action, note }),
  deals: () => call<DealRow[]>("/deals"),
  createDeal: (name: string) => call<DealRow>("/deals", "POST", { name }),
  setStage: (name: string, stage: string) => call<DealRow>(`/deals/${encodeURIComponent(name)}`, "PATCH", { stage }),
  dd: (deal: string) => call<DDRow[]>(`/dd/requests?deal=${encodeURIComponent(deal)}`),
  ddSeed: (deal: string) => call<{ created: number }>("/dd/requests/seed", "POST", { deal }),
  ddStatus: (id: number, status: string) => call<DDRow>(`/dd/requests/${id}`, "PATCH", { status }),
  report: () => call<Report>("/portfolio/report"),
  evals: () => call<EvalRunRow[]>("/evals?limit=200"),
};

export const STAGES = ["sourcing", "screening", "dd", "ic", "signed", "closed", "passed"];
