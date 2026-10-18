import { useState } from "react";
import { api2, CitedFigure, RollForward as Roll, SubmissionRow } from "./api";
import { Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** Opening mark to closing mark for one company. The change is withheld when any input is missing or hidden, and every input names its document. */
export function RollForward() {
  const [period, setPeriod] = useState("");
  const [prior, setPrior] = useState("");
  const [markMetric, setMarkMetric] = useState("");
  const [companies, setCompanies] = useState<SubmissionRow[] | null>(null);
  const [companyId, setCompanyId] = useState<number | null>(null);
  const [roll, setRoll] = useState<Roll | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const loadCompanies = () => {
    if (!period.trim()) return;
    setBusy(true); setErr("");
    api2.portfolioSubmissions(period.trim())
      .then((r) => setCompanies([...r.submitted, ...r.missing].sort((a, b) => a.name.localeCompare(b.name))))
      .catch((x) => { setCompanies(null); setErr(String(x)); })
      .finally(() => setBusy(false));
  };

  const load = (id: number) => {
    if (!prior.trim()) { setErr("Enter the prior period to roll forward from."); return; }
    setCompanyId(id); setBusy(true); setErr("");
    api2.rollForward(id, period.trim(), prior.trim(), markMetric.trim() || undefined)
      .then(setRoll)
      .catch((x) => { setRoll(null); setErr(String(x)); })
      .finally(() => setBusy(false));
  };

  return (
    <Page title="Roll-forward" hint="Opening mark to closing mark for one company. A change in value appears only when every input is on file and visible to you.">
      <Card>
        <CardHead title="Periods" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => { e.preventDefault(); loadCompanies(); }}>
          <label className="flex flex-col gap-1 text-xs text-mut">Period<Input value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="2026-09" /></label>
          <label className="flex flex-col gap-1 text-xs text-mut">Prior period<Input value={prior} onChange={(e) => setPrior(e.target.value)} placeholder="2026-08" /></label>
          <label className="flex flex-col gap-1 text-xs text-mut">Mark metric, optional<Input value={markMetric} onChange={(e) => setMarkMetric(e.target.value)} placeholder="equity_value" /></label>
          <Button variant="primary" type="submit" disabled={!period.trim() || busy}>Load companies</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {companies && companies.length === 0 && <Empty>No portfolio companies yet.</Empty>}
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
      {roll && (
        <Card>
          <CardHead title={`${roll.prior} to ${roll.period}`} />
          <table className="w-full text-sm">
            <tbody>
              <Row label="Opening mark" f={roll.opening} />
              <Row label="Cash in" f={roll.contributions} />
              <Row label="Cash out" f={roll.distributions} />
              <Row label="Closing mark" f={roll.closing} />
            </tbody>
          </table>
          <div className="border-t border-line p-5 text-sm">
            <span className="text-mut">Change in value: </span>
            {roll.change_in_value == null
              ? <span className="text-mut">withheld, an input is missing or not visible to you</span>
              : <span className="font-mono">{roll.change_in_value}</span>}
          </div>
        </Card>
      )}
    </Page>
  );
}

/** One line of the roll-forward: its label, then the cited figure, or "not on file". */
function Row({ label, f }: { label: string; f: CitedFigure | null }) {
  return (
    <tr className="border-t border-line align-top">
      <td className="p-3 text-mut">{label}</td>
      <td className="p-3">
        {!f ? <span className="text-mut">not on file</span> : (
          <div className="space-y-0.5">
            <div className="font-mono text-xs">{f.value}</div>
            {f.url
              ? <a className="text-xs text-acc" href={f.url} target="_blank" rel="noreferrer">{f.source}</a>
              : <div className="text-xs text-mut">{f.source}</div>}
          </div>
        )}
      </td>
    </tr>
  );
}
