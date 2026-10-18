import { useState } from "react";
import { api2, BudgetMetric, CitedFigure, SubmissionRow } from "./api";
import { Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** One company's actuals against its budget for a period. Each figure names the document it was read from and links to it when the source has a link. */
export function BudgetVsActual() {
  const [period, setPeriod] = useState("");
  const [companies, setCompanies] = useState<SubmissionRow[] | null>(null);
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [metrics, setMetrics] = useState<BudgetMetric[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const loadCompanies = () => {
    if (!period.trim()) return;
    setBusy(true); setErr(""); setMetrics(null);
    api2.portfolioSubmissions(period.trim())
      .then((r) => setCompanies([...r.submitted, ...r.missing].sort((a, b) => a.name.localeCompare(b.name))))
      .catch((x) => { setCompanies(null); setErr(String(x)); })
      .finally(() => setBusy(false));
  };

  const load = (id: number) => {
    setCompanyId(id); setBusy(true); setErr("");
    api2.budgetVsActual(id, period.trim())
      .then((r) => setMetrics(r.metrics))
      .catch((x) => { setMetrics(null); setErr(String(x)); })
      .finally(() => setBusy(false));
  };

  return (
    <Page title="Budget vs actual" hint="Actuals against budget for one company and period. Every figure names the document it was read from.">
      <Card>
        <CardHead title="Period" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => { e.preventDefault(); loadCompanies(); }}>
          <label className="flex flex-col gap-1 text-xs text-mut">Period<Input value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="2026-08" /></label>
          <Button variant="primary" type="submit" disabled={!period.trim() || busy}>Load companies</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {companies && companies.length === 0 && <Empty>No portfolio companies yet. A company appears here once one of its verified KPIs is tracked.</Empty>}
      {companies && companies.length > 0 && (
        <Card>
          <CardHead title="Company" />
          <div className="flex flex-wrap gap-2 p-5">
            {companies.map((c) => (
              <Button key={c.company_id} onClick={() => load(c.company_id)} disabled={busy}
                variant={companyId === c.company_id ? "primary" : "default"}>{c.name}</Button>
            ))}
          </div>
        </Card>
      )}
      {metrics && metrics.length === 0 && <Empty>No actual or budget figure on file for this company and period.</Empty>}
      {metrics && metrics.length > 0 && (
        <Card>
          <CardHead title="Metrics" hint={`${metrics.length} shown`} />
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-mut"><th className="p-3">Metric</th><th>Actual</th><th>Budget</th><th>Variance</th><th>Of budget</th></tr></thead>
            <tbody>{metrics.map((m) => (
              <tr key={m.metric} className="border-t border-line align-top">
                <td className="p-3">{m.metric} <span className="text-xs text-mut">{m.unit}</span></td>
                <td><Figure f={m.actual} /></td>
                <td><Figure f={m.budget} /></td>
                <td className="font-mono text-xs">{m.variance ?? "n/a"}</td>
                <td className="font-mono text-xs">{m.variance_pct == null ? "n/a" : `${m.variance_pct}%`}</td>
              </tr>))}</tbody>
          </table>
        </Card>
      )}
    </Page>
  );
}

/** One cited figure: the value, then the document it was read from, linked when the source has a link. */
function Figure({ f }: { f: CitedFigure | null }) {
  if (!f) return <span className="text-mut">not on file</span>;
  return (
    <div className="space-y-0.5">
      <div className="font-mono text-xs">{f.value}</div>
      {f.url
        ? <a className="text-xs text-acc" href={f.url} target="_blank" rel="noreferrer">{f.source}</a>
        : <div className="text-xs text-mut">{f.source}</div>}
    </div>
  );
}
