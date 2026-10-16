import { FileUp, Search } from "lucide-react";
import { useState } from "react";
import { api, DocumentInfo, Hit } from "./api";
import { useLoad } from "./hooks";
import { SourceChip } from "./source";
import { Button, Card, CardHead, Empty, ErrorLine, Input } from "./ui";

export function Documents() {
  const docs = useLoad<DocumentInfo[]>(api.documents);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [entity, setEntity] = useState("");
  const [memo, setMemo] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (f: () => Promise<void>) => { setErr(""); try { await f(); } catch (e) { setErr(String(e)); } };
  const name = (id: string) => docs.data?.find((d) => d.id === id)?.filename ?? id.slice(0, 8);
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-6">
      <div><h1 className="text-xl font-semibold tracking-tight">Documents</h1><p className="text-sm text-mut">PDF, Excel, Word, PowerPoint, email, CSV, ZIP and UK iXBRL filings.</p></div>
      <ErrorLine e={err || docs.error} />
      <Card>
        <CardHead title="Library" right={
          <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-acc px-3 py-1.5 text-sm font-medium text-bg hover:opacity-90">
            <FileUp size={15} />{busy ? "Uploading..." : "Upload"}
            <input type="file" className="sr-only" aria-label="Upload a document" accept=".pdf,.xlsx,.docx,.pptx,.eml,.zip,.csv,.html"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) { setBusy(true); void run(async () => { await api.upload(f); docs.reload(); }).finally(() => setBusy(false)); } }} />
          </label>} />
        {docs.data?.length === 0 && <Empty>No documents yet. Upload a CIM, a 10-K or a spreadsheet to begin.</Empty>}
        <ul className="divide-y divide-line">
          {docs.data?.map((d) => (
            <li key={d.id} className="flex items-center gap-3 px-5 py-2.5 text-sm"><span className="min-w-0 flex-1 truncate font-medium">{d.filename}</span>
              <span className="tnum text-mut">{d.n_pages} pages</span><SourceChip docId={d.id} page={1} quote="" label="Open" /></li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardHead title="Search" hint="Ranked pages across every document" />
        <form className="flex gap-2 p-4" onSubmit={(e) => { e.preventDefault(); void run(async () => setHits(await api.search(q))); }}>
          <Input className="flex-1" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. capital expenditure" aria-label="Search" />
          <Button variant="primary" type="submit"><Search size={15} />Search</Button>
        </form>
        {hits?.length === 0 && <Empty>Nothing found. An empty result is an answer, not an error.</Empty>}
        <ul className="divide-y divide-line">
          {hits?.map((h) => (
            <li key={`${h.document_id}-${h.page}`} className="flex items-start gap-3 px-5 py-2.5 text-sm">
              <SourceChip docId={h.document_id} page={h.page} quote={q} label={`${name(h.document_id).slice(0, 24)} p.${h.page}`} />
              <span className="min-w-0 flex-1 text-mut">{h.snippet.slice(0, 160)}</span></li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardHead title="IC memo draft" hint="Verified facts only, every figure footnoted to its page" />
        <form className="flex gap-2 p-4" onSubmit={(e) => { e.preventDefault(); void run(async () => setMemo((await api.memo(entity)).markdown)); }}>
          <Input className="flex-1" value={entity} onChange={(e) => setEntity(e.target.value)} placeholder="Entity name" aria-label="Entity" />
          <Button variant="primary" type="submit">Build memo</Button>
        </form>
        {memo && <pre className="mx-4 mb-4 overflow-x-auto whitespace-pre-wrap rounded-lg bg-sunk p-3 font-mono text-[12px]">{memo}</pre>}
      </Card>
    </div>
  );
}
