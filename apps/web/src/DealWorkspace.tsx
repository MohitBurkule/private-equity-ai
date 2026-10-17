import { useState } from "react";
import { api, api2, dealNotes, DealSnapshot, LegalOut } from "./api";
import { useLoad } from "./hooks";
import { SourceChip } from "./source";
import { Badge, Button, Card, CardHead, Empty, ErrorLine } from "./ui";
import { NotesPanel } from "./Notes";

const TYPES = [["nda", "NDA"], ["spa", "SPA"], ["credit", "Credit agreement"]] as const;

/** Everything about one deal in one place: diligence progress, its documents, and key legal terms per document. */
export function DealWorkspace({ deal }: { deal: string }) {
  const docs = useLoad(() => api.documents().then((d) => d.filter((x) => x.deal === deal)), [deal]);
  const sum = useLoad(() => api2.ddSummary(deal).catch(() => null), [deal]);
  const snap = useLoad(() => api2.snapshot(deal).catch(() => null), [deal]);
  const [legal, setLegal] = useState<Record<string, LegalOut>>({});
  const [type, setType] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const run = (id: string) => {
    setErr("");
    api2.legalTerms(id, type[id] ?? "nda").then((r) => setLegal({ ...legal, [id]: r })).catch((e) => setErr(String(e)));
  };
  const cats = sum.data ? Object.entries(sum.data.by_category) : [];
  // Findings the playbook marks for review, across every document whose legal terms were run on this page.
  const redFlags = Object.values(legal).flatMap((r) => r.findings.filter((f) => f.needs_review));
  const docName = new Map((docs.data ?? []).map((d) => [d.id, d.filename] as const));
  return (
    <>
    {snap.data && <SnapshotCard s={snap.data} />}
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
      {redFlags.length > 0 && (
        <div className="border-t border-line p-5">
          <p className="mb-2 text-sm font-medium">Red flags to review</p>
          <table className="w-full text-sm"><thead className="text-left text-xs text-mut"><tr><th className="pb-1">Document</th><th>Term</th><th>Value</th><th className="text-right">Page</th></tr></thead>
            <tbody>{redFlags.map((f, i) => (
              <tr key={`${f.document_id}-${f.term}-${i}`} className="border-t border-line">
                <td className="py-1.5">{docName.get(f.document_id) ?? f.document_id.slice(0, 8)}</td>
                <td>{f.term.replace(/_/g, " ")}</td>
                <td className="tnum">{f.value}</td>
                <td className="tnum text-right">{f.page}</td>
              </tr>
            ))}</tbody></table>
        </div>
      )}
    </Card>
    <div className="mt-4"><NotesPanel title="Deal notes" hint="Shared with everyone who can see this deal" api={dealNotes(deal)} deps={[deal]} /></div>
    </>
  );
}

/** The partner's one-page view: where the deal stands, what changed since IC, and what is still open. */
function SnapshotCard({ s }: { s: DealSnapshot }) {
  const cells: [string, string][] = [
    ["Stage", s.stage],
    ["Sponsor", s.sponsor ?? "not recorded"],
    ["Last IC", s.ic.latest ? s.ic.latest.outcome : "none recorded"],
    ["Dissents on file", String(s.ic.dissents)],
    ["Filed since IC", String(s.ic.changed_since_ic)],
    ["DD closed", s.dd.pct_complete == null ? "no requests" : `${s.dd.pct_complete}%`],
    ["Documents", String(s.documents.count)],
    ["Open alerts", String(s.open_alerts)],
  ];
  return (
    <Card>
      <CardHead title="Snapshot" hint="Where this deal stands, from the same records as the sections below" right={s.legal_hold && <Badge tone="warn">legal hold</Badge>} />
      <dl className="grid grid-cols-2 gap-3 p-5 sm:grid-cols-4">
        {cells.map(([k, v]) => (
          <div key={k} className="min-w-0"><dt className="text-xs text-mut">{k}</dt><dd className="truncate text-sm font-medium capitalize">{v}</dd></div>
        ))}
      </dl>
      {s.ic.changed_documents.length > 0 && (
        <p className="border-t border-line px-5 py-3 text-xs text-mut">
          Changed since last IC: {s.ic.changed_documents.map((d) => d.filename).join(", ")}
        </p>
      )}
    </Card>
  );
}
