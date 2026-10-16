import { useEffect, useState } from "react";
import { api, AskResult, DocumentInfo, Hit, PageData } from "./api";
import { splitAtQuote } from "./highlight";

const friendly = (e: string) => e.includes("503") ? "This needs an AI model, and none is configured on this server. Everything else still works." : e;

export function Workspace() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [docId, setDocId] = useState<string>("");
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[]>([]);
  const [page, setPage] = useState<PageData | null>(null);
  const [quote, setQuote] = useState("");
  const [entity, setEntity] = useState("");
  const [memo, setMemo] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<AskResult | null>(null);
  const [error, setError] = useState("");
  
  const run = async (f: () => Promise<void>) => {
    setError("");
    try { await f(); } catch (e) { setError(String(e)); }
  };
  const refresh = () => run(async () => setDocs(await api.documents()));
  useEffect(() => { void refresh(); }, []);

  const open = (d: string, n: number) => run(async () => setPage(await api.page(d, n)));
  const parts = page && quote ? splitAtQuote(page.text, quote) : null;

  return (
    <main>
      {error && <p role="alert" className="alert">{friendly(error)}</p>}

      <section className="panel">
        <h2>Documents</h2>
        <input type="file" aria-label="Upload a document" accept=".pdf,.xlsx,.docx,.pptx,.eml,.zip,.csv,.html" onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void run(async () => { await api.upload(f); await refresh(); });
        }} />
        <ul className="list">
          {docs.map((d) => (
            <li key={d.id}>
              <button onClick={() => { setDocId(d.id); void open(d.id, 1); }}>{d.filename}</button> ({d.n_pages} pages)
            </li>
          ))}
        </ul>
      </section>

      <section className="panel">
        <h2>Search{docId ? " (scoped to selected document)" : " (all documents)"}</h2>
        <form className="row" onSubmit={(e) => { e.preventDefault(); void run(async () => setHits(await api.search(q, docId || undefined))); }}>
          <input value={q} aria-label="Search" onChange={(e) => setQ(e.target.value)} placeholder="e.g. capital expenditure" />
          <button type="submit">Search</button>
        </form>
        {hits.length === 0 && q && <p>Nothing found. (An empty result is an answer, not an error.)</p>}
        <ol className="list">
          {hits.map((h) => (
            <li key={`${h.document_id}-${h.page}`}>
              <button onClick={() => { setDocId(h.document_id); setQuote(q); void open(h.document_id, h.page); }}>
                p.{h.page}
              </button> score {h.score}: {h.snippet.slice(0, 120)}
            </li>
          ))}
        </ol>
      </section>

      <section className="panel">
        <h2>Ask</h2>
        <form className="row" onSubmit={(e) => { e.preventDefault(); void run(async () => setAnswer(await api.ask(question, docId || undefined))); }}>
          <input value={question} aria-label="Question" onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about the documents" />
          <button type="submit">Ask</button>
        </form>
        {answer && answer.status === "not_found" && (
          <p>Not found in the documents. Nothing was verified against a source. {answer.detail}</p>
        )}
        {answer && answer.status === "error" && <p role="alert">{answer.detail}</p>}
        <ul className="list">
          {answer?.claims.map((c, i) => (
            <li key={i}>
              {c.text}{" "}
              <button onClick={() => { setDocId(c.document_id); setQuote(c.quote); void open(c.document_id, c.page); }}>
                source p.{c.page}
              </button>
            </li>
          ))}
        </ul>
        {answer && answer.rejected.length > 0 && (
          <details>
            <summary>{answer.rejected.length} claim(s) rejected by verification</summary>
            <ul>{answer.rejected.map((c, i) => <li key={i}>{c.text}: {c.reason}</li>)}</ul>
          </details>
        )}
      </section>

      {page && (
        <section className="panel">
          <h2>Source: page {page.page}</h2>
          {page.method === "ocr" && (
            <p role="alert" className="pill warn">
              Text recognised from a scan (confidence {Math.round((page.ocr_confidence ?? 0) * 100)}%). Check figures against the image; facts from this page are not marked verified.
            </p>
          )}
          {page.text.startsWith("[UNRELIABLE") && (
            <p role="alert" className="alert">
              This filing failed its own arithmetic checks. Do not rely on its figures.
            </p>
          )}
          <label>Highlight quote <input value={quote} onChange={(e) => setQuote(e.target.value)} /></label>
          {quote && !parts && <p>Quote not found on this page.</p>}
          <pre className="src">
            {parts ? (<>{parts.before}<mark>{parts.match}</mark>{parts.after}</>) : page.text}
          </pre>
        </section>
      )}

      <section className="panel">
        <h2>IC memo draft</h2>
        <form className="row" onSubmit={(e) => { e.preventDefault(); void run(async () => setMemo((await api.memo(entity)).markdown)); }}>
          <input value={entity} aria-label="Entity" onChange={(e) => setEntity(e.target.value)} placeholder="Entity name" />
          <button type="submit">Build memo</button>
        </form>
        {memo && <pre className="src">{memo}</pre>}
      </section>
    </main>
  );
}
