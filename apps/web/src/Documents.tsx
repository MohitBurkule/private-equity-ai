import { FileUp, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { api, DocumentInfo, Hit } from "./api";
import { useLoad } from "./hooks";
import { filterDocs } from "./libraryFilter";
import { loadViews, saveViews, SavedView } from "./savedViews";
import { SourceChip } from "./source";
import { Button, Card, CardHead, Empty, ErrorLine, Input, Loading } from "./ui";

export function Documents() {
  const docs = useLoad<DocumentInfo[]>(api.documents);
  const [libQ, setLibQ] = useState("");
  // "/" jumps to the library filter, the usual search key, but never steals a key typed into another field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (e.key !== "/" || e.metaKey || e.ctrlKey || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const el = document.getElementById("library-filter");
      if (el) { e.preventDefault(); el.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  const [views, setViews] = useState<SavedView[]>(() => loadViews());
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [targetDeal, setTargetDeal] = useState("");
  const [bulkNote, setBulkNote] = useState("");
  const [left, setLeft] = useState("");
  const [right, setRight] = useState("");
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
        {docs.loading && <Loading />}
        {docs.data?.length === 0 && <Empty>No documents yet. Upload a CIM, a 10-K or a spreadsheet to begin.</Empty>}
        {docs.data && docs.data.length > 0 && (
          <div className="px-4 pt-3">
            <Input id="library-filter" className="w-full" value={libQ} onChange={(e) => setLibQ(e.target.value)} placeholder="Filter by filename (press /)" aria-label="Filter documents" />
          </div>
        )}
        {docs.data && docs.data.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 px-4 pt-2 text-sm">
            <Button disabled={!libQ.trim()} onClick={() => {
              const name = libQ.trim();
              const next = [...views.filter((v) => v.name !== name), { name, query: name }];
              setViews(next);
              saveViews(next);
            }}>Save this filter</Button>
            {views.map((v) => (
              <span key={v.name} className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5">
                <button className="hover:underline" onClick={() => setLibQ(v.query)}>{v.name}</button>
                <button aria-label={`Remove view ${v.name}`} className="text-mut hover:text-acc"
                  onClick={() => { const next = views.filter((x) => x.name !== v.name); setViews(next); saveViews(next); }}>×</button>
              </span>
            ))}
          </div>
        )}
        {docs.data && docs.data.length > 0 && filterDocs(docs.data, libQ).length === 0 && <Empty>No document name matches "{libQ}".</Empty>}
        {picked.size > 0 && (
          <div className="flex flex-wrap items-center gap-2 px-4 pt-3 text-sm">
            <span className="text-mut">{picked.size} selected</span>
            <Input value={targetDeal} onChange={(e) => setTargetDeal(e.target.value)} placeholder="Deal name (blank = no deal)" aria-label="Target deal" />
            <Button disabled={busy} onClick={() => void run(async () => {
              setBusy(true);
              try {
                const out = await api.bulkDeal([...picked], targetDeal.trim() || null);
                setBulkNote(`Moved ${out.moved.length}. Refused ${out.refused.length}${out.refused.length ? `: ${out.refused.map((x) => x.reason).join("; ")}` : ""}.`);
                setPicked(new Set());
                docs.reload();
              } finally { setBusy(false); }
            })}>Move selected</Button>
            {bulkNote && <span className="text-mut">{bulkNote}</span>}
          </div>
        )}
        <ul className="divide-y divide-line">
          {filterDocs(docs.data ?? [], libQ).map((d) => (
            <li key={d.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
              <input type="checkbox" aria-label={`Select ${d.filename}`} checked={picked.has(d.id)}
                onChange={(e) => setPicked((prev) => { const next = new Set(prev); if (e.target.checked) next.add(d.id); else next.delete(d.id); return next; })} />
              <span className="min-w-0 flex-1 truncate font-medium">{d.filename}</span>
              <span className="tnum text-mut">{d.n_pages} pages</span><SourceChip docId={d.id} page={1} quote="" label="Open" /></li>
          ))}
        </ul>
      </Card>
      {docs.data && docs.data.length > 1 && (
        <Card>
          <CardHead title="Compare" hint="Two documents side by side, each opening at its first page" />
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            {[{ label: "Left", value: left, set: setLeft }, { label: "Right", value: right, set: setRight }].map((side) => {
              const doc = docs.data?.find((d) => d.id === side.value);
              return (
                <div key={side.label} className="min-w-0 space-y-2">
                  <select aria-label={`${side.label} document`} value={side.value} onChange={(e) => side.set(e.target.value)}
                    className="w-full rounded-lg border border-line bg-sunk px-2 py-1.5 text-sm">
                    <option value="">Choose a document</option>
                    {docs.data?.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
                  </select>
                  {doc && (
                    <div className="text-sm">
                      <div className="truncate font-medium">{doc.filename}</div>
                      <div className="tnum text-mut">{doc.n_pages} pages</div>
                      <SourceChip docId={doc.id} page={1} quote="" label="Open first page" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      )}
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
