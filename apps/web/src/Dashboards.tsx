import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api2, DealRow, Report, STAGES } from "./api";
import { fmtAmount } from "./format";
import { useLoad } from "./hooks";
import { SourceChip } from "./source";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Loading } from "./ui";

const tip = { background: "var(--c-panel)", border: "1px solid var(--c-line)", borderRadius: 8, fontSize: 12 };

/** KPI by period for one metric, optionally one company. Click a bar to see its source. */
function KpiBoard({ report }: { report: Report }) {
  const metrics = useMemo(() => [...new Set(report.companies.flatMap((c) => c.kpis.map((k) => k.metric)))], [report]);
  const [metric, setMetric] = useState("");
  const [company, setCompany] = useState("all");
  const [period, setPeriod] = useState("all");
  const [pick, setPick] = useState<number | null>(null);
  const m = metric || metrics[0] || "";
  const periods = useMemo(() => [...new Set(report.companies.flatMap((c) => c.kpis.map((k) => k.period)))].sort(), [report]);
  const rows = report.companies.filter((c) => company === "all" || String(c.id) === company)
    .flatMap((c) => c.kpis.filter((k) => k.metric === m && (period === "all" || k.period === period)).map((k) => ({ ...k, company: c.name })))
    .sort((a, b) => a.period.localeCompare(b.period) || a.company.localeCompare(b.company));
  const unit = rows[0]?.unit ?? "";
  const data = rows.map((r) => ({ label: `${r.company.slice(0, 18)} ${r.period}`, v: Number(r.value) }));
  const sel = pick !== null ? rows[pick] : null;
  const [grid, setGrid] = useState(false);
  const [cell, setCell] = useState<{ company: string; period: string; value: string; unit: string; src?: { document_id: string; page: number } } | null>(null);
  // Quarterly board: one row per company, one column per period, every cell a cited fact for the chosen metric.
  const board = report.companies.filter((c) => company === "all" || String(c.id) === company)
    .map((c) => ({ name: c.name, cells: new Map(c.kpis.filter((k) => k.metric === m).map((k) => [k.period, k])) }));
  return (
    <Card>
      <CardHead title="Portfolio KPIs by period" hint="Every bar or cell is a cited fact. Click one to open its source."
        right={<div className="flex flex-wrap gap-2">
          <button onClick={() => setGrid((g) => !g)} className="rounded-lg border border-line px-2 py-1 text-sm">{grid ? "Bars" : "Board"}</button>
          <select aria-label="Metric" value={m} onChange={(e) => { setMetric(e.target.value); setPick(null); }} className="rounded-lg border border-line bg-bg px-2 py-1 text-sm">
            {metrics.map((x) => <option key={x}>{x}</option>)}</select>
          <select aria-label="Company" value={company} onChange={(e) => { setCompany(e.target.value); setPick(null); }} className="rounded-lg border border-line bg-bg px-2 py-1 text-sm">
            <option value="all">All companies</option>{report.companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <select aria-label="Period" value={period} onChange={(e) => { setPeriod(e.target.value); setPick(null); }} className="rounded-lg border border-line bg-bg px-2 py-1 text-sm">
            <option value="all">All periods</option>{periods.map((p) => <option key={p}>{p}</option>)}</select>
        </div>} />
      {rows.length === 0 ? <Empty>No KPI observations for this filter. Try another metric, company or period, or record one from a verified fact.</Empty> : grid ? (
        <div className="overflow-x-auto p-5">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-mut"><th className="pr-4 font-medium">Company</th>
              {periods.filter((p) => period === "all" || p === period).map((p) => <th key={p} className="px-2 font-medium">{p}</th>)}</tr></thead>
            <tbody>{board.map((b) => (
              <tr key={b.name} className="border-t border-line">
                <td className="py-2 pr-4">{b.name}</td>
                {periods.filter((p) => period === "all" || p === period).map((p) => {
                  const k = b.cells.get(p);
                  return <td key={p} className="tnum px-2 py-2">{k ? (
                    <button onClick={() => setCell({ company: b.name, period: p, value: k.value, unit: k.unit, src: k.sources[0] })}
                      className="underline decoration-dotted underline-offset-4">{fmtAmount(k.value, k.unit)}</button>) : <span className="text-mut">—</span>}</td>;
                })}
              </tr>))}</tbody>
          </table>
          {cell && (
            <p className="mt-3 flex items-center gap-2 text-sm">
              <b>{cell.company}</b> {m} {cell.period}: <span className="tnum">{fmtAmount(cell.value, cell.unit)}</span>
              {cell.src && <SourceChip docId={cell.src.document_id} page={cell.src.page} quote="" />}
            </p>
          )}
          <p className="mt-2 text-xs text-mut">A dash means no observation for that period. Nothing is estimated.</p>
        </div>
      ) : (
        <div className="p-5">
          <div className="h-64">
            <ResponsiveContainer>
              <BarChart data={data} aria-label="KPI values by period">
                <CartesianGrid stroke="var(--c-line)" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: "var(--c-mut)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <YAxis tickFormatter={(v: number) => fmtAmount(String(v), unit)} tick={{ fill: "var(--c-mut)", fontSize: 11 }} axisLine={false} tickLine={false} width={64} />
                <Tooltip contentStyle={tip} formatter={(v) => fmtAmount(String(v), unit)} cursor={{ fill: "var(--c-sunk)" }} />
                <Bar dataKey="v" radius={[4, 4, 0, 0]} onClick={(_, i) => setPick(i)} cursor="pointer">
                  {data.map((_, i) => <Cell key={i} fill={i === pick ? "var(--c-fg)" : "var(--c-acc)"} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          {sel && (
            <p className="mt-3 flex items-center gap-2 text-sm">
              <b>{sel.company}</b> {sel.metric} {sel.period}: <span className="tnum">{fmtAmount(sel.value, sel.unit)}</span>
              {sel.sources[0] && <SourceChip docId={sel.sources[0].document_id} page={sel.sources[0].page} quote="" />}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

/** Deal pipeline by stage; click a stage to filter the table under it. */
function Pipeline({ deals }: { deals: DealRow[] }) {
  const [stage, setStage] = useState("");
  const data = STAGES.map((s) => ({ stage: s, n: deals.filter((d) => d.stage === s).length }));
  const shown = deals.filter((d) => !stage || d.stage === stage);
  return (
    <Card>
      <CardHead title="Deal pipeline" hint="Click a stage to filter" right={stage && <Button variant="ghost" onClick={() => setStage("")}>Clear filter</Button>} />
      <div className="h-44 px-5 pt-4">
        <ResponsiveContainer>
          <BarChart data={data} aria-label="Deals per stage">
            <XAxis dataKey="stage" tick={{ fill: "var(--c-mut)", fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis allowDecimals={false} hide />
            <Tooltip contentStyle={tip} cursor={{ fill: "var(--c-sunk)" }} />
            <Bar dataKey="n" radius={[4, 4, 0, 0]} cursor="pointer" onClick={(d) => setStage((d as unknown as { stage: string }).stage)}>
              {data.map((d) => <Cell key={d.stage} fill={d.stage === stage ? "var(--c-fg)" : "var(--c-acc)"} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-[11px] uppercase tracking-wider text-mut"><th className="px-5 py-2">Deal</th><th>Stage</th><th className="text-right">Docs</th><th className="px-5 text-right">DD open</th></tr></thead>
        <tbody>
          {shown.map((d) => (
            <tr key={d.name} className="border-t border-line"><td className="px-5 py-2 font-medium">{d.name}</td><td><Badge tone="acc">{d.stage}</Badge></td>
              <td className="tnum text-right">{d.documents}</td><td className="tnum px-5 text-right">{d.dd_open}/{d.dd_total}</td></tr>
          ))}
          {shown.length === 0 && <tr><td colSpan={4}><Empty>No deals at this stage.</Empty></td></tr>}
        </tbody>
      </table>
    </Card>
  );
}

export function Dashboards() {
  const report = useLoad<Report>(api2.report);
  const deals = useLoad<DealRow[]>(api2.deals);
  return (
    <div className="mx-auto max-w-5xl space-y-5 p-6">
      <div><h1 className="text-xl font-semibold tracking-tight">Dashboards</h1><p className="text-sm text-mut">Click through any chart to the deal or the source page behind it.</p></div>
      <ErrorLine e={report.error || deals.error} />
      {report.loading && <Loading />}
      {report.data && <KpiBoard report={report.data} />}
      {deals.loading && <Loading />}
      {deals.data && <Pipeline deals={deals.data} />}
    </div>
  );
}
