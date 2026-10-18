import { useEffect, useState } from "react";
import { api, api2, DDQuestionRow, DocumentInfo } from "./api";
import { useLoad } from "./hooks";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";
import { SourceChip } from "./source";

/** Management Q&A for a deal. An answer must cite a document, a page and a quote the server finds on that page. */
export function DDQa() {
  const [deal, setDeal] = useState("");
  const [rows, setRows] = useState<DDQuestionRow[]>([]);
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [draft, setDraft] = useState("");
  const [answers, setAnswers] = useState<Record<number, { text: string; doc: string; page: string; quote: string }>>({});
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
          <label className="flex flex-col gap-1 text-xs text-mut">Deal name<Input value={deal} onChange={(e) => setDeal(e.target.value)} placeholder="Deal" /></label>
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
        const a = answers[r.id] ?? { text: "", doc: "", page: "", quote: "" };
        return (
          <Card key={r.id}>
            <div className="space-y-2 p-5">
              <div className="flex items-start justify-between gap-3">
                <p className="text-sm font-medium">{r.question}</p>
                <Badge tone={r.status === "answered" ? "ok" : "warn"}>{r.status}</Badge>
              </div>
              {r.status === "answered" && (
                <p className="text-sm">{r.answer}{" "}
                  {r.document_id && r.page !== null && r.quote && (
                    <SourceChip docId={r.document_id} page={r.page} quote={r.quote} label={docName(r.document_id)} />)}
                </p>
              )}
              {r.status === "open" && (
                <form className="flex flex-wrap gap-2" onSubmit={(e) => {
                  e.preventDefault();
                  api2.ddQuestionAnswer(r.id, { answer: a.text.trim(), document_id: a.doc, page: Number(a.page), quote: a.quote.trim() })
                    .then(load).catch((x) => setErr(String(x)));
                }}>
                  <Input className="flex-1" value={a.text} placeholder="Answer" onChange={(e) => setAnswers({ ...answers, [r.id]: { ...a, text: e.target.value } })} />
                  <select aria-label="Source document" className="rounded-md border border-line bg-panel px-2 text-sm" value={a.doc}
                    onChange={(e) => setAnswers({ ...answers, [r.id]: { ...a, doc: e.target.value } })}>
                    <option value="">Choose document</option>
                    {docs.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
                  </select>
                  <Input className="w-20" aria-label="Page" type="number" min={1} value={a.page} placeholder="Page"
                    onChange={(e) => setAnswers({ ...answers, [r.id]: { ...a, page: e.target.value } })} />
                  <Input className="w-full" aria-label="Quote" value={a.quote} placeholder="Quote printed on that page"
                    onChange={(e) => setAnswers({ ...answers, [r.id]: { ...a, quote: e.target.value } })} />
                  <Button type="submit" disabled={!a.text.trim() || !a.doc || !a.page || !a.quote.trim()}>Record answer</Button>
                </form>
              )}
            </div>
          </Card>
        );
      })}
    </Page>
  );
}
