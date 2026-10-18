import { api2, DDRow, DealRow, EvalRunRow, FactRow, Report, STAGES } from "./api";
import { fmtAmount } from "./format";
import { useLoad } from "./hooks";
import { SourceChip } from "./source";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Loading, Page } from "./ui";
import { useState } from "react";
import { DealWorkspace } from "./DealWorkspace";
import { covenantBadge, covenantTestCount } from "./covenantSummary";
import { pushRecentDeal } from "./recentDeals";


export function ReviewQueue() {
  const { data, error, loading, reload, setError } = useLoad<FactRow[]>(async () => [
    ...(await api2.facts("auto")), ...(await api2.facts("ocr_unverified")),
  ]);
  const conflicts = useLoad(api2.conflicts);
  const act = (id: number, action: "accept" | "reject") => api2.review(id, action).then(reload).catch((e) => setError(String(e)));
  return (
    <Page title="Review" hint="Extracted facts need an analyst before they can appear in a memo.">
      <Card>
        <CardHead title="Waiting for review" />
        <ErrorLine e={error} />
        {loading && <Loading />}
        {data?.length === 0 && <Empty>Nothing waiting for review.</Empty>}
        <ul className="divide-y divide-line">
          {data?.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{f.entity} · {f.metric} · {f.period}: <span className="tnum">{fmtAmount(f.value, f.unit)}</span> <Badge tone="warn">{f.status}</Badge></p>
                {f.sources[0] && <p className="mt-1 flex items-center gap-2 text-xs text-mut"><SourceChip docId={f.sources[0].document_id} page={f.sources[0].page} quote={f.sources[0].quote} />“{f.sources[0].quote}”</p>}
              </div>
              <Button variant="primary" onClick={() => void act(f.id, "accept")}>Accept</Button>
              <Button onClick={() => void act(f.id, "reject")}>Reject</Button>
            </li>
          ))}
        </ul>
      </Card>
      <Card>
        <CardHead title="Conflicts between documents" hint="Same metric and period, different values. Each value sits beside its own source. Nothing is picked for you." />
        {conflicts.loading && <Loading />}
        {conflicts.data?.length === 0 && <Empty>No conflicts found.</Empty>}
        <ul className="divide-y divide-line">
          {conflicts.data?.map((c, i) => (
            <li key={i} className="px-5 py-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium">{c.entity} · {c.metric} · {c.period}</span>
                <Badge tone={c.severity === "material" ? "bad" : c.severity === "minor" ? "warn" : "acc"}>{c.severity}</Badge>
                {c.cross_document && <Badge tone="warn">across documents</Badge>}
                <span className="text-xs text-mut">spread {c.spread_pct}%</span>
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {c.sources.map((src) => (
                  <div key={src.fact_id} className="rounded-lg border border-line p-3">
                    <p className="tnum text-sm font-medium">{fmtAmount(src.value, "")}</p>
                    {src.documents.slice(0, 1).map((d) => (
                      <p key={d.document_id} className="mt-1.5 flex flex-wrap items-center gap-2 text-xs text-mut">
                        <SourceChip docId={d.document_id} page={d.page} quote={d.quote} label={`${(d.filename ?? "doc").slice(0, 22)} p.${d.page}`} />
                      </p>
                    ))}
                  </div>
                ))}
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </Page>
  );
}

/** `initial` selects a deal when the screen opens, e.g. from a recent-deal palette entry. */
export function Deals({ initial = "" }: { initial?: string }) {
  const [name, setName] = useState("");
  const [sel, setSel] = useState(initial);
  const deals = useLoad<DealRow[]>(api2.deals);
  const dd = useLoad<DDRow[]>(async () => (sel ? api2.dd(sel) : []), [sel]);
  const fail = (e: unknown) => deals.setError(String(e));
  const byCat = new Map<string, DDRow[]>();
  dd.data?.forEach((r) => byCat.set(r.category, [...(byCat.get(r.category) ?? []), r]));
  return (
    <Page title="Deals" hint="Pipeline and the due-diligence request list for each deal.">
      <Card>
        <CardHead title="Pipeline" right={
          <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (!name.trim()) return; api2.createDeal(name).then(() => { setName(""); deals.reload(); }).catch(fail); }}>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="New deal name" aria-label="New deal name" /><Button variant="primary" type="submit">Create</Button>
          </form>} />
        <ErrorLine e={deals.error || dd.error} />
        {deals.loading && <Loading />}
        {deals.data?.length === 0 && <Empty>No deals yet. Create one to start a diligence list.</Empty>}
        <table className="w-full text-sm">
          <tbody>
            {deals.data?.map((d) => (
              <tr key={d.name} className={"cursor-pointer border-t border-line first:border-0 hover:bg-sunk " + (sel === d.name ? "bg-acc-soft" : "")} onClick={() => { setSel(d.name); pushRecentDeal(d.name); }}>
                <td className="px-5 py-3 font-medium">{d.name}</td>
                <td><select aria-label={`Stage of ${d.name}`} value={d.stage} onClick={(e) => e.stopPropagation()} onChange={(e) => api2.setStage(d.name, e.target.value).then(deals.reload).catch(fail)} className="rounded-md border border-line bg-bg px-2 py-1">
                  {STAGES.map((s) => <option key={s}>{s}</option>)}</select></td>
                <td className="tnum text-mut">{d.documents} docs</td>
                <td className="tnum px-5 text-right">{d.dd_total ? `${d.dd_total - d.dd_open}/${d.dd_total} received` : "no list"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      {sel && <DealWorkspace deal={sel} />}
      {sel && (
        <Card>
          <CardHead title={`Due diligence: ${sel}`} right={<Button onClick={() => api2.ddSeed(sel).then(dd.reload).catch(fail)}>Add standard request list</Button>} />
          {dd.loading && <Loading />}
          {dd.data?.length === 0 && <Empty>No requests yet. Use "Add standard request list" to seed the usual ones.</Empty>}
          {[...byCat.entries()].map(([cat, rows]) => (
            <div key={cat} className="border-t border-line first:border-0">
              <p className="bg-sunk px-5 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-mut">{cat.replace("_", " / ")}</p>
              <ul>{rows.map((r) => (
                <li key={r.id} className="flex items-center gap-3 px-5 py-2 text-sm">
                  <span className="min-w-0 flex-1">{r.title}</span>
                  <select aria-label={`Status of ${r.title}`} value={r.status} onChange={(e) => api2.ddStatus(r.id, e.target.value).then(dd.reload).catch(fail)} className="rounded-md border border-line bg-bg px-2 py-1">
                    {["open", "received", "waived"].map((s) => <option key={s}>{s}</option>)}</select>
                </li>))}</ul>
            </div>
          ))}
        </Card>
      )}
    </Page>
  );
}

export function PortfolioPanel() {
  const { data, error, loading } = useLoad<Report>(api2.report);
  const tests = data ? covenantTestCount(data.companies) : 0;
  return (
    <Page title="Portfolio" hint="Every KPI is tied to a cited fact. Covenants test those KPIs against cited thresholds.">
      <ErrorLine e={error} />
      <Card>
        <CardHead title="Covenant alerts" right={data && <Badge tone={data.breaches.length ? "bad" : tests ? "ok" : "mut"}>{covenantBadge(data, tests)}</Badge>} />
        {loading && <Loading />}
        {data?.breaches.length === 0 && <Empty>{tests ? "No breaches in the visible tests." : data.companies.length ? "No covenant tests have run yet. Add one on a company's Covenants tab, with a cited threshold." : "No portfolio companies yet. A company appears here once one of its verified KPIs is tracked."}</Empty>}
        <ul className="divide-y divide-line">
          {data?.breaches.map((b, i) => (
            <li key={i} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
              <Badge tone="bad">{b.status}</Badge><span className="font-medium">{b.company}</span>
              <span className="text-mut">{b.kpi_metric} · {b.period}</span>
              <span className="tnum ml-auto">{fmtAmount(b.value, b.unit ?? "")} vs limit {fmtAmount(b.threshold, b.unit ?? "")}</span>
            </li>
          ))}
        </ul>
      </Card>
      {data?.companies.map((c) => (
        <Card key={c.id}>
          <CardHead title={c.name} />
          {c.kpis.length === 0 && <Empty>No visible KPI observations.</Empty>}
          <table className="w-full text-sm"><tbody>
            {c.kpis.map((k, i) => (
              <tr key={i} className="border-t border-line first:border-0"><td className="px-5 py-2">{k.metric}</td><td className="text-mut">{k.period}</td>
                <td className="tnum text-right font-medium">{fmtAmount(k.value, k.unit)}</td>
                <td className="px-5 text-right">{k.sources[0] && <SourceChip docId={k.sources[0].document_id} page={k.sources[0].page} quote="" />}</td></tr>
            ))}
          </tbody></table>
        </Card>
      ))}
    </Page>
  );
}

const isNum = (v: unknown): v is number => typeof v === "number";

export function EvalDashboard() {
  const { data, error, loading } = useLoad<EvalRunRow[]>(api2.evals);
  const bySuite = new Map<string, EvalRunRow[]>();
  data?.forEach((r) => bySuite.set(r.suite, [...(bySuite.get(r.suite) ?? []), r]));
  return (
    <Page title="Evals" hint="How well the system itself performs, tracked run over run.">
      <ErrorLine e={error} />
      {loading && <Loading />}
      {data?.length === 0 && <Card><Empty>No eval runs recorded. Run evals/record.py to add some.</Empty></Card>}
      {[...bySuite.entries()].map(([suite, runs]) => {
        const latest = runs[0];
        const numeric = Object.entries(latest.metrics).filter(([, v]) => isNum(v));
        const misses = latest.metrics["misses"];
        return (
          <Card key={suite}>
            <CardHead title={suite} hint={`Latest run ${latest.ran_at.slice(0, 19).replace("T", " ")}${latest.note ? ` · ${latest.note}` : ""} · ${runs.length} run(s)`} />
            <table className="w-full text-sm">
              <thead><tr className="text-left text-[11px] uppercase tracking-wider text-mut"><th className="px-5 py-2">Metric</th><th className="text-right">Latest</th><th className="px-5 text-right">Previous</th></tr></thead>
              <tbody>{numeric.map(([k, v]) => {
                const prev = runs[1]?.metrics[k];
                return <tr key={k} className="border-t border-line"><td className="px-5 py-2">{k}</td><td className="tnum text-right font-medium">{String(v)}</td><td className="tnum px-5 text-right text-mut">{isNum(prev) ? String(prev) : "-"}</td></tr>;
              })}</tbody>
            </table>
            {Array.isArray(misses) && misses.length > 0 && (
              <details className="border-t border-line px-5 py-3 text-xs"><summary>{misses.length} miss(es) in the latest run</summary><pre className="mt-2 overflow-x-auto">{JSON.stringify(misses, null, 1)}</pre></details>
            )}
          </Card>
        );
      })}
    </Page>
  );
}
