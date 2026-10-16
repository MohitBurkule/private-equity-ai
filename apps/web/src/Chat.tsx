import { Search, SendHorizonal, Sparkles } from "lucide-react";
import { useRef, useState } from "react";
import { api, api2, AskResult, DocumentInfo, Hit } from "./api";
import { SourceChip } from "./source";
import { Badge, Button, Card } from "./ui";

type Turn =
  | { who: "user"; text: string }
  | { who: "agent"; question: string; answer?: AskResult; hits: Hit[]; docs: Record<string, string>; note?: string; tools?: string[] };

const SUGGESTIONS = [
  "What was net income for the nine months?",
  "Show total liabilities and where it comes from",
  "Any covenant or debt terms I should flag?",
];

/** Agent chat. Runs document search first (always works), then asks the model for a verified, cited answer. */
export function Chat() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  const send = async (text: string) => {
    if (!text.trim() || busy) return;
    setQ(""); setBusy(true);
    setTurns((t) => [...t, { who: "user", text }]);
    const docs: Record<string, string> = {};
    let hits: Hit[] = [];
    let answer: AskResult | undefined;
    let note: string | undefined;
    let tools: string[] | undefined;
    try {
      const list: DocumentInfo[] = await api.documents();
      list.forEach((d) => { docs[d.id] = d.filename; });
      hits = (await api.search(text)).slice(0, 5);
      try {
        const run = await api2.agent(text);
        tools = run.steps.map((s) => s.tool);
        if (run.status === "done" && run.result && "claims" in run.result) answer = run.result as unknown as AskResult;
        else throw new Error("agent-failed");
      } catch (e) {
        if (String(e).includes("503")) {
          note = "No AI model is configured on this server, so there is no written answer. These are the closest passages in your documents.";
        } else {
          // Small models often cannot drive the agent loop; a direct verified ask is the reliable path.
          try { answer = await api.ask(text); } catch (e2) { note = String(e2); }
        }
      }
    } catch (e) { note = String(e); }
    setTurns((t) => [...t, { who: "agent", question: text, answer, hits, docs, note, tools }]);
    setBusy(false);
    setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 50);
  };

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col px-6">
      <div className="flex-1 space-y-5 overflow-y-auto py-8">
        {turns.length === 0 && (
          <div className="mt-12 text-center">
            <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-2xl bg-acc-soft text-acc"><Sparkles size={22} /></div>
            <h1 className="text-xl font-semibold tracking-tight">Ask anything across your deal documents</h1>
            <p className="mx-auto mt-2 max-w-md text-sm text-mut">Every answer links to the page and quote it came from. If it cannot be verified, it says so.</p>
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {SUGGESTIONS.map((s) => <Button key={s} onClick={() => void send(s)}>{s}</Button>)}
            </div>
          </div>
        )}
        {turns.map((t, i) => t.who === "user" ? (
          <div key={i} className="flex justify-end"><div className="max-w-[80%] rounded-2xl rounded-br-md bg-acc px-4 py-2.5 text-bg">{t.text}</div></div>
        ) : (
          <Card key={i} className="space-y-3 p-4">
            {t.tools && t.tools.length > 0 && (
              <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-mut">Used {t.tools.map((n, k) => <Badge key={k} tone="acc">{n}</Badge>)}</p>
            )}
            {t.answer?.status === "not_found" && <p className="text-sm">Not found in the documents. Nothing was verified against a source. {t.answer.detail}</p>}
            {t.answer?.status === "error" && <p role="alert" className="text-sm text-bad">{t.answer.detail}</p>}
            {t.answer?.claims.map((c, k) => (
              <p key={k} className="text-sm leading-relaxed">{c.text}{" "}<SourceChip docId={c.document_id} page={c.page} quote={c.quote} /></p>
            ))}
            {t.answer && t.answer.rejected.length > 0 && (
              <details className="text-xs text-mut"><summary>{t.answer.rejected.length} claim(s) dropped by verification</summary>
                <ul className="mt-1 list-disc pl-5">{t.answer.rejected.map((c, k) => <li key={k}>{c.text}: {c.reason}</li>)}</ul></details>
            )}
            {t.note && <p className="text-sm text-mut">{t.note}</p>}
            {t.hits.length > 0 && (
              <div>
                <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-mut"><Search size={11} />Passages searched</p>
                <ul className="divide-y divide-line rounded-lg border border-line">
                  {t.hits.map((h) => (
                    <li key={`${h.document_id}-${h.page}`} className="flex items-start gap-2 px-3 py-2 text-xs">
                      <SourceChip docId={h.document_id} page={h.page} quote="" label={`${(t.docs[h.document_id] ?? "doc").slice(0, 22)} p.${h.page}`} />
                      <span className="min-w-0 flex-1 text-mut">{h.snippet.slice(0, 140)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {t.hits.length === 0 && !t.answer && <Badge tone="warn">Nothing found</Badge>}
          </Card>
        ))}
        {busy && <p className="text-sm text-mut">Searching your documents...</p>}
        <div ref={end} />
      </div>
      <form className="pb-6" onSubmit={(e) => { e.preventDefault(); void send(q); }}>
        <div className="flex items-center gap-2 rounded-2xl border border-line bg-panel p-2 shadow-sm">
          <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Question" placeholder="Ask about a deal, a metric, a clause..."
            className="min-w-0 flex-1 bg-transparent px-3 py-2 text-sm outline-none placeholder:text-mut" />
          <Button variant="primary" type="submit" disabled={busy || !q.trim()} aria-label="Send"><SendHorizonal size={16} /></Button>
        </div>
      </form>
    </div>
  );
}
