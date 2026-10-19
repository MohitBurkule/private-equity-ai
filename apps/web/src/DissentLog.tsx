import { useEffect, useState } from "react";
import { api2, ICDecisionRow } from "./api";
import { Badge, Card, CardHead, Empty, ErrorLine, Page } from "./ui";

/** Every recorded IC dissent across the firm, newest first. Only deals this key may see are listed. */
export function DissentLog() {
  const [rows, setRows] = useState<ICDecisionRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api2.dissentLog().then(setRows).catch((e: unknown) => setError(String(e)));
  }, []);

  return (
    <Page title="Dissent log" hint="Every recorded IC dissent across the firm, newest first, with the deal and the decision it was filed against.">
      <Card>
        <CardHead title="Dissents" right={rows && <Badge tone="mut">{rows.length} on file</Badge>} />
        <ErrorLine e={error} />
        {rows === null && !error && <Empty>Loading...</Empty>}
        {rows?.length === 0 && <Empty>No dissents recorded. Dissent is only logged when an IC decision records one.</Empty>}
        <ul className="divide-y divide-line">
          {rows?.map((r) => (
            <li key={r.id} className="space-y-1 px-5 py-3 text-sm">
              <div className="flex flex-wrap items-center gap-3">
                <span className="min-w-0 flex-1 font-medium">{r.deal}</span>
                <Badge tone="mut">{r.outcome}</Badge>
                <span className="text-xs text-mut">{r.recorded_at.slice(0, 10)} · decision #{r.id}</span>
              </div>
              <p>{r.dissent}</p>
              {r.dissenter && <p className="text-xs text-mut">Dissent by {r.dissenter}</p>}
            </li>
          ))}
        </ul>
      </Card>
    </Page>
  );
}
