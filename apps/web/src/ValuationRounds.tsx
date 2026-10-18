import { useState } from "react";
import { api, ValuationRound } from "./api";
import { useLoad } from "./hooks";
import { SourceChip } from "./source";
import { Card, CardHead, Empty, ErrorLine, Input, Loading, Page } from "./ui";

/** Round and valuation history from uploaded exports. Each row opens the file it came from; the CSV line is shown as text. */
export function ValuationRounds() {
  const [company, setCompany] = useState("");
  const rounds = useLoad<ValuationRound[]>(() => api.valuationRounds());
  const shown = (rounds.data ?? []).filter((r) => !company.trim() || r.company.toLowerCase().includes(company.trim().toLowerCase()));
  return (
    <Page title="Valuation history" hint="Rounds and marks from your uploaded exports, oldest first. Every row opens its source file.">
      <ErrorLine e={rounds.error} />
      <Card>
        <CardHead title="Rounds" right={<Input value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Filter by company" aria-label="Filter by company" />} />
        {rounds.loading && <Loading />}
        {rounds.data && rounds.data.length === 0 && <Empty>No rounds yet. Import a valuation export to see history here.</Empty>}
        {shown.length === 0 && (rounds.data?.length ?? 0) > 0 && <Empty>No company matches "{company}".</Empty>}
        <ul className="divide-y divide-line text-sm">
          {shown.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 px-5 py-2.5">
              <span className="tnum text-mut">{r.round_date}</span>
              <span className="min-w-0 flex-1 font-medium">{r.company}</span>
              <span className="text-mut">{r.round_type}</span>
              <span className="tnum">{Number(r.post_money).toLocaleString("en-GB")} {r.currency}</span>
              <SourceChip docId={r.document_id} page={1} quote="" label={`Source, line ${r.line}`} />
            </li>
          ))}
        </ul>
      </Card>
    </Page>
  );
}
