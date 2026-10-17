import { useEffect, useState } from "react";
import { api, api2, DDQuestionRow, DocumentInfo } from "./api";
import { useLoad } from "./hooks";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** Management Q&A for a deal. An answer can cite a document; the cite is the document the answer came from, not a quote. */
export function DDQa() {
  const [deal, setDeal] = useState("");
  const [rows, setRows] = useState<DDQuestionRow[]>([]);
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [draft, setDraft] = useState("");
  const [answers, setAnswers] = useState<Record<number, { text: string; doc: string }>>({});
  const [err, setErr] = useState("");
  const docName = (id: string | null) => docs.find((d) => d.id === id)?.filename ?? id ?? "";

  useEffect(() => { void api.documents().then(setDocs).catch(() => setDocs([])); }, []);

  const load = () => {
    if (!deal) return;
    api2.ddQuestions(deal).then(setRows).catch((e) => setErr(String(e)));
  };

  return (
    <Page title="DD Q&A" hint="Questions to management and the seller. Answers cite the document they came from.">
      <Card>
        <CardHead title="Deal" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => { e.preventDefault(); setErr(""); load(); }}>
          <label className="text-xs text-mut">Deal name<Input className="mt-1" value={deal} onChange={(e) => setDeal(e.target.value)} placeholder="Deal" /></label>
          <Button variant="primary" type="submit" disabled={!deal}>Load log</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {deal && (
        <Card>
          <CardHead title="Ask" />
          <form className="flex gap-3 p-5" onSubmit={(e) => {
            e.preventDefault(); if (!draft.trim()) return;
            api2.ddQuestionAdd(deal, draft.trim()).then(() => { setDraft(""); load(); }).catch((x) => setErr(String(x)));
          }}>
            <Input className="flex-1" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Question for management" />
            <Button variant="primary" type="submit" disabled={!draft.trim()}>Add</Button>
          </form>
        </Card>
      )}
      {rows.length === 0 && deal ? <Empty>No questions logged for this deal.</Empty> : null}
      {rows.map((r) => {
        const a = answers[r.id] ?? { text: "", doc: "" };
        return (
          <Card key={r.id}>
            <div className="space-y-2 p-5">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-medium">{r.question}</p>
                <Badge tone={r.status === "answered" ? "ok" : "warn"}>{r.status}</Badge>
              </div>
              {r.status === "answered" && (
                <p className="text-sm">{r.answer}{r.document_id && <span className="ml-2 text-xs text-mut">source: {docName(r.document_id)}</span>}</p>
              )}
              {r.status === "open" && (
                <form className="flex flex-wrap gap-2" onSubmit={(e) => {
                  e.preventDefault(); if (!a.text.trim()) return;
                  api2.ddQuestionAnswer(r.id, a.text.trim(), a.doc || null).then(load).catch((x) => setErr(String(x)));
                }}>
                  <Input className="flex-1" value={a.text} placeholder="Answer" onChange={(e) => setAnswers({ ...answers, [r.id]: { ...a, text: e.target.value } })} />
                  <select aria-label="Source document" className="rounded-md border border-line bg-panel px-2 text-sm" value={a.doc}
                    onChange={(e) => setAnswers({ ...answers, [r.id]: { ...a, doc: e.target.value } })}>
                    <option value="">No document</option>
                    {docs.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
                  </select>
                  <Button type="submit" disabled={!a.text.trim()}>Record answer</Button>
                </form>
              )}
            </div>
          </Card>
        );
      })}
    </Page>
  );
}
