import { useState } from "react";
import { api, AccessReport as Report } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";
import { SourceChip } from "./source";

/** Who did what to one deal, from the audit trail. Needs a key with govern on that deal; the server enforces it. */
export function AccessReport() {
  const [deal, setDeal] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Page title="Deal access report" hint="Logged actions on one deal and who took them. Document reads are not logged, so they do not appear here.">
      <Card>
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => {
          e.preventDefault(); if (!deal.trim()) return;
          setBusy(true); setErr("");
          api.accessReport(deal.trim()).then(setReport).catch((x) => { setReport(null); setErr(String(x)); }).finally(() => setBusy(false));
        }}>
          <label className="flex flex-col gap-1 text-xs text-mut">Deal name<Input value={deal} onChange={(e) => setDeal(e.target.value)} /></label>
          <Button variant="primary" type="submit" disabled={!deal.trim() || busy}>{busy ? "Loading" : "Run report"}</Button>
        </form>
      </Card>
      <ErrorLine e={err} />
      {report && (
        <Card>
          <CardHead title={report.deal} hint={report.note} />
          {report.events.length === 0 && <Empty>No logged actions on this deal.</Empty>}
          <div className="flex flex-wrap gap-1 px-5 pt-3">
            {Object.entries(report.by_actor).map(([actor, n]) => <Badge key={actor} tone="mut">{actor}: {n}</Badge>)}
          </div>
          <ul className="divide-y divide-line text-sm">
            {report.events.map((e, i) => (
              <li key={i} className="flex flex-wrap items-center gap-3 px-5 py-2.5">
                <span className="tnum text-mut">{e.ts}</span>
                <span className="font-medium">{e.action}</span>
                <span className="text-mut">{e.actor}</span>
                {typeof e.payload.doc_id === "string" && <SourceChip docId={e.payload.doc_id} page={1} quote="" label="Open document" />}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
  );
}
