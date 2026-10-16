import { useState } from "react";
import { api, api2, LegalOut } from "./api";
import { useLoad } from "./hooks";
import { SourceChip } from "./source";
import { Badge, Button, Card, CardHead, Empty, ErrorLine } from "./ui";

const TYPES = [["nda", "NDA"], ["spa", "SPA"], ["credit", "Credit agreement"]] as const;

/** Everything about one deal in one place: diligence progress, its documents, and key legal terms per document. */
export function DealWorkspace({ deal }: { deal: string }) {
  const docs = useLoad(() => api.documents().then((d) => d.filter((x) => x.deal === deal)), [deal]);
  const sum = useLoad(() => api2.ddSummary(deal).catch(() => null), [deal]);
  const [legal, setLegal] = useState<Record<string, LegalOut>>({});
  const [type, setType] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const run = (id: string) => {
    setErr("");
    api2.legalTerms(id, type[id] ?? "nda").then((r) => setLegal({ ...legal, [id]: r })).catch((e) => setErr(String(e)));
  };
  const cats = sum.data ? Object.entries(sum.data.by_category) : [];
  return (
    <Card>
      <CardHead title={`Workspace: ${deal}`} hint="Progress, documents and key legal terms" right={sum.data?.pct_complete != null && <Badge tone="acc">{sum.data.pct_complete}% of requests closed</Badge>} />
      <ErrorLine e={err || docs.error} />
      {cats.length > 0 && (
        <div className="grid gap-3 border-b border-line p-5 sm:grid-cols-3">
          {cats.map(([c, n]) => {
            const total = n.open + n.received + n.waived;
            return (
              <div key={c}><p className="mb-1 flex justify-between text-xs"><span className="capitalize">{c.replace("_", " / ")}</span><span className="tnum text-mut">{total - n.open}/{total}</span></p>
                <div className="h-1.5 overflow-hidden rounded-full bg-sunk"><div className="h-full bg-acc" style={{ width: `${(100 * (total - n.open)) / total}%` }} /></div></div>
            );
          })}
        </div>
      )}
      {docs.data?.length === 0 && <Empty>No documents tagged to this deal yet. Upload with the deal name or import from an integration.</Empty>}
      <ul className="divide-y divide-line">
        {docs.data?.map((d) => (
          <li key={d.id} className="px-5 py-3">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span className="min-w-0 flex-1 truncate font-medium">{d.filename}</span><span className="tnum text-mut">{d.n_pages} {d.n_pages === 1 ? "page" : "pages"}</span>
              <SourceChip docId={d.id} page={1} quote="" label="Open" />
              <select aria-label={`Document type of ${d.filename}`} value={type[d.id] ?? "nda"} onChange={(e) => setType({ ...type, [d.id]: e.target.value })} className="rounded-md border border-line bg-bg px-2 py-1">
                {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
              <Button onClick={() => run(d.id)}>Extract key terms</Button>
            </div>
            {legal[d.id] && (
              <div className="mt-3 rounded-lg border border-line">
                {legal[d.id].findings.length === 0 && <p className="px-3 py-2 text-xs text-mut">No terms matched. Nothing was guessed.</p>}
                {legal[d.id].findings.map((f, i) => (
                  <div key={i} className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2 text-xs last:border-0">
                    <span className="w-44 shrink-0 font-medium">{f.term.replace(/_/g, " ")}</span><span className="tnum">{f.value}</span>
                    {f.needs_review && <Badge tone="warn">needs a human</Badge>}
                    <SourceChip docId={f.document_id} page={f.page} quote={f.quote} />
                  </div>
                ))}
                {legal[d.id].absent.length > 0 && <p className="px-3 py-2 text-xs text-mut">Not found: {legal[d.id].absent.map((a) => a.replace(/_/g, " ")).join(", ")}</p>}
              </div>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
