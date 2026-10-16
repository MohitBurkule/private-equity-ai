import { useEffect, useState } from "react";
import { api, AskResult, DocumentInfo, getApiKey, Hit, PageData, setApiKey } from "./api";
import { splitAtQuote } from "./highlight";

export function App() {
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
  const [key, setKey] = useState(getApiKey());

  const run = async (f: () => Promise<void>) => {
    setError("");
    try { await f(); } catch (e) { setError(String(e)); }
  };
  const refresh = () => run(async () => setDocs(await api.documents()));
  useEffect(() => { void refresh(); }, []);

  const open = (d: string, n: number) => run(async () => setPage(await api.page(d, n)));
  const parts = page && quote ? splitAtQuote(page.text, quote) : null;

  return (
    <main style={{ fontFamily: "system-ui", maxWidth: 1100, margin: "0 auto", padding: 16 }}>
      <h1>PE Platform</h1>
      <label>
        API key{" "}
        <input type="password" value={key} onChange={(e) => { setKey(e.target.value); setApiKey(e.target.value); }}
          onBlur={() => void refresh()} placeholder="pe_..." />
      </label>
      {error && <p role="alert" style={{ color: "crimson" }}>{error}</p>}

      <section>
        <h2>Documents</h2>
        <input type="file" accept=".pdf,.xlsx,.docx,.pptx,.eml,.zip,.csv,.html" onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void run(async () => { await api.upload(f); await refresh(); });
        }} />
        <ul>
          {docs.map((d) => (
            <li key={d.id}>
              <button onClick={() => { setDocId(d.id); void open(d.id, 1); }}>{d.filename}</button> ({d.n_pages} pages)
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Search{docId ? " (scoped to selected document)" : " (all documents)"}</h2>
        <form onSubmit={(e) => { e.preventDefault(); void run(async () => setHits(await api.search(q, docId || undefined))); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. capital expenditure" style={{ width: "60%" }} />
          <button type="submit">Search</button>
        </form>
        {hits.length === 0 && q && <p>Nothing found. (An empty result is an answer, not an error.)</p>}
        <ol>
          {hits.map((h) => (
            <li key={`${h.document_id}-${h.page}`}>
              <button onClick={() => { setDocId(h.document_id); setQuote(q); void open(h.document_id, h.page); }}>
                p.{h.page}
              </button> score {h.score}: {h.snippet.slice(0, 120)}
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2>Ask</h2>
        <form onSubmit={(e) => { e.preventDefault(); void run(async () => setAnswer(await api.ask(question, docId || undefined))); }}>
          <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask about the documents" style={{ width: "60%" }} />
          <button type="submit">Ask</button>
        </form>
        {answer && answer.status === "not_found" && (
          <p>Not found in the documents. Nothing was verified against a source. {answer.detail}</p>
        )}
        {answer && answer.status === "error" && <p role="alert">{answer.detail}</p>}
        <ul>
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
        <section>
          <h2>Source: page {page.page}</h2>
          {page.method === "ocr" && (
            <p role="alert" style={{ color: "darkorange", fontWeight: 600 }}>
              Text recognised from a scan (confidence {Math.round((page.ocr_confidence ?? 0) * 100)}%). Check figures against the image; facts from this page are not marked verified.
            </p>
          )}
          {page.text.startsWith("[UNRELIABLE") && (
            <p role="alert" style={{ color: "crimson", fontWeight: 600 }}>
              This filing failed its own arithmetic checks. Do not rely on its figures.
            </p>
          )}
          <label>Highlight quote <input value={quote} onChange={(e) => setQuote(e.target.value)} /></label>
          {quote && !parts && <p>Quote not found on this page.</p>}
          <pre style={{ whiteSpace: "pre-wrap", background: "#f6f6f6", padding: 12 }}>
            {parts ? (<>{parts.before}<mark>{parts.match}</mark>{parts.after}</>) : page.text}
          </pre>
        </section>
      )}

      <section>
        <h2>IC memo draft</h2>
        <form onSubmit={(e) => { e.preventDefault(); void run(async () => setMemo((await api.memo(entity)).markdown)); }}>
          <input value={entity} onChange={(e) => setEntity(e.target.value)} placeholder="Entity name" />
          <button type="submit">Build memo</button>
        </form>
        {memo && <pre style={{ whiteSpace: "pre-wrap" }}>{memo}</pre>}
      </section>
    </main>
  );
}
