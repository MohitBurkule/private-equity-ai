export interface DocumentInfo { id: string; filename: string; n_pages: number }
export interface Hit { document_id: string; page: number; score: number; snippet: string }
export interface PageData { document_id: string; page: number; text: string }

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  documents: () => fetch("/api/documents").then((r) => j<DocumentInfo[]>(r)),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/documents", { method: "POST", body: fd }).then((r) => j<DocumentInfo>(r));
  },
  search: (q: string, docId?: string) =>
    fetch(`/api/search?q=${encodeURIComponent(q)}${docId ? `&doc_id=${docId}` : ""}`).then((r) => j<Hit[]>(r)),
  page: (docId: string, n: number) => fetch(`/api/documents/${docId}/pages/${n}`).then((r) => j<PageData>(r)),
  memo: (entity: string) =>
    fetch(`/api/memo?entity=${encodeURIComponent(entity)}`).then((r) => j<{ markdown: string }>(r)),
};
