export interface DocumentInfo { id: string; filename: string; n_pages: number }
export interface Hit { document_id: string; page: number; score: number; snippet: string }
export interface PageData { document_id: string; page: number; text: string }

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
  memo: (entity: string) =>
    fetch(`/api/memo?entity=${encodeURIComponent(entity)}`, { headers: auth() }).then((r) => j<{ markdown: string }>(r)),
};
