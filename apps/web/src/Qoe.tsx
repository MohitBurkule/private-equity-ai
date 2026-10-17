import { useState } from "react";
import { api2, NwcPeg, QoeCalc, TrendRow } from "./api";
import { fmtAmount } from "./format";
import { Button, Card, CardHead, Empty, ErrorLine, Input } from "./ui";
import { SourceChip } from "./source";

/** Quality of earnings from cited facts. A figure with a gap shows the gap; every input links to its source. */
export function Qoe() {
  const [entity, setEntity] = useState("");
  const [period, setPeriod] = useState("FY24");
  const [periods, setPeriods] = useState("FY22, FY23, FY24");
  const [ebitda, setEbitda] = useState<QoeCalc | null>(null);
  const [peg, setPeg] = useState<NwcPeg | null>(null);
  const [trend, setTrend] = useState<TrendRow[]>([]);
  const [err, setErr] = useState("");

  const run = async () => {
    setErr("");
    const ps = periods.split(",").map((p) => p.trim()).filter(Boolean).join(",");
    try {
      const [e, p, t] = await Promise.all([api2.qoeEbitda(entity, period), api2.nwcPeg(entity, ps), api2.revenueTrend(entity, ps)]);
      setEbitda(e); setPeg(p); setTrend(t.rows);
    } catch (x) { setErr(String(x)); }
  };

  const flagged = ebitda?.one_off_flags ?? [];
  const inputFor = (factId: number) => ebitda?.inputs.find((i) => i.fact_id === factId);

  return (
    <div className="mx-auto max-w-4xl space-y-5 p-6">
      <div><h1 className="text-xl font-semibold tracking-tight">Quality of earnings</h1>
        <p className="text-sm text-mut">Normalized EBITDA, NWC peg and trend, computed from verified, cited facts. Unreviewed bridge lines withhold the total.</p></div>
      <Card>
        <CardHead title="Entity and periods" />
        <form className="grid gap-3 p-5 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); void run(); }}>
          <label className="text-xs text-mut">Entity<Input className="mt-1 w-full" value={entity} onChange={(e) => setEntity(e.target.value)} placeholder="Company" /></label>
          <label className="text-xs text-mut">Period<Input className="mt-1 w-full" value={period} onChange={(e) => setPeriod(e.target.value)} /></label>
          <label className="text-xs text-mut">Periods for peg and trend<Input className="mt-1 w-full" value={periods} onChange={(e) => setPeriods(e.target.value)} /></label>
          <div className="sm:col-span-3"><Button variant="primary" type="submit" disabled={!entity}>Run QoE</Button></div>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {ebitda && (
        <Card>
          <CardHead title="Normalized EBITDA" hint={ebitda.formula} />
          <div className="space-y-3 p-5">
            {ebitda.ok
              ? <p className="text-lg font-semibold">{fmtAmount(ebitda.value ?? "", ebitda.unit ?? "")}</p>
              : <p className="text-sm text-mut">Withheld: {ebitda.missing.concat(ebitda.problems).join("; ")}</p>}
            {ebitda.inputs.map((i) => (
              <p key={i.fact_id} className="text-sm">{i.role} ({i.sign > 0 ? "+" : "-"}): {fmtAmount(i.value, i.unit)}{" "}
                {i.sources[0] && <SourceChip docId={i.sources[0].document_id} page={i.sources[0].page} quote={i.sources[0].quote} />}</p>
            ))}
            {flagged.length > 0 && (
              <div>
                <p className="text-xs font-medium text-mut">Possible one-offs (add-backs above 10% of reported EBITDA)</p>
                {flagged.map((f) => {
                  const src = inputFor(f.fact_id)?.sources[0];
                  return <p key={f.fact_id} className="text-sm">{fmtAmount(f.amount, "USD")}{" "}
                    {src && <SourceChip docId={src.document_id} page={src.page} quote={src.quote} />}</p>;
                })}
              </div>
            )}
          </div>
        </Card>
      )}
      {peg && (
        <Card>
          <CardHead title="NWC peg" hint={peg.formula} />
          <div className="p-5 text-sm">
            {peg.ok ? <p className="text-lg font-semibold">{fmtAmount(peg.value ?? "", "USD")}</p>
              : <p className="text-mut">Withheld: {peg.missing.concat(peg.problems).join("; ")}</p>}
            {Object.entries(peg.per_period ?? {}).map(([p, c]) => (
              <p key={p} className="text-mut">{p}: {c.ok ? fmtAmount(c.value ?? "", "USD") : "withheld"}</p>
            ))}
          </div>
        </Card>
      )}
      {trend.length > 0 ? (
        <Card>
          <CardHead title="Revenue and margin trend" />
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-mut"><th className="p-3">Period</th><th>Revenue</th><th>Growth</th><th>EBITDA margin</th></tr></thead>
            <tbody>{trend.map((r) => (
              <tr key={r.period} className="border-t border-line">
                <td className="p-3">{r.period}</td>
                <td>{r.revenue ? fmtAmount(r.revenue, "USD") : "-"}</td>
                <td>{r.growth_pct ? `${r.growth_pct}%` : "-"}</td>
                <td>{r.ebitda_margin_pct ? `${r.ebitda_margin_pct}%` : <span className="text-mut">{r.missing[0] ?? "-"}</span>}</td>
              </tr>))}</tbody>
          </table>
        </Card>
      ) : !err && <Empty>Run QoE to see the trend.</Empty>}
    </div>
  );
}
