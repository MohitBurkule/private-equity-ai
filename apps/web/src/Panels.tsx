import { useEffect, useState } from "react";
import { fmtAmount } from "./format";
import { api2, DDRow, EvalRunRow, DealRow, FactRow, Report, STAGES } from "./api";

function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = () => { setError(""); load().then(setData).catch((e) => setError(String(e))); };
  useEffect(reload, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, reload, setError };
}

const Err = ({ e }: { e: string }) => (e ? <p role="alert" className="alert">{e}</p> : null);

export function ReviewQueue() {
  const { data, error, reload, setError } = useLoad<FactRow[]>(async () => [
    ...(await api2.facts("auto")), ...(await api2.facts("ocr_unverified")),
  ]);
  const act = (id: number, action: "accept" | "reject") =>
    api2.review(id, action).then(reload).catch((e) => setError(String(e)));
  return (
    <section className="panel">
      <h2>Review queue</h2>
      <Err e={error} />
      {data && data.length === 0 && <p>Nothing waiting for review.</p>}
      <ul className="list">
        {data?.map((f) => (
          <li key={f.id}>
            <b>{f.entity} {f.metric} {f.period}</b>: {fmtAmount(f.value, f.unit)} <span className="pill warn">{f.status}</span>
            {f.sources[0] && <blockquote>“{f.sources[0].quote}” (doc {f.sources[0].document_id.slice(0, 8)}, p.{f.sources[0].page})</blockquote>}
            <button onClick={() => void act(f.id, "accept")}>Accept</button>{" "}
            <button onClick={() => void act(f.id, "reject")}>Reject</button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Deals() {
  const [name, setName] = useState("");
  const [sel, setSel] = useState("");
  const deals = useLoad<DealRow[]>(api2.deals);
  const dd = useLoad<DDRow[]>(async () => (sel ? api2.dd(sel) : []), [sel]);
  const fail = (e: unknown) => deals.setError(String(e));
  return (
    <section className="panel">
      <h2>Deals</h2>
      <Err e={deals.error || dd.error} />
      <form className="row" onSubmit={(e) => { e.preventDefault(); api2.createDeal(name).then(() => { setName(""); deals.reload(); }).catch(fail); }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New deal name" />
        <button type="submit">Create</button>
      </form>
      <table>
        <thead><tr><th>Deal</th><th>Stage</th><th>Docs</th><th>DD open</th></tr></thead>
        <tbody>
          {deals.data?.map((d) => (
            <tr key={d.name}>
              <td><button onClick={() => setSel(d.name)}>{d.name}</button></td>
              <td>
                <select value={d.stage} onChange={(e) => api2.setStage(d.name, e.target.value).then(deals.reload).catch(fail)}>
                  {STAGES.map((s) => <option key={s}>{s}</option>)}
                </select>
              </td>
              <td>{d.documents}</td><td>{d.dd_open}/{d.dd_total}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {sel && (
        <>
          <h3>DD tracker: {sel}</h3>
          <button onClick={() => api2.ddSeed(sel).then(dd.reload).catch(fail)}>Add standard request list</button>
          <ul className="list">
            {dd.data?.map((r) => (
              <li key={r.id}>
                [{r.category}] {r.title}{" "}
                <select value={r.status} onChange={(e) => api2.ddStatus(r.id, e.target.value).then(dd.reload).catch(fail)}>
                  {["open", "received", "waived"].map((s) => <option key={s}>{s}</option>)}
                </select>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export function PortfolioPanel() {
  const { data, error } = useLoad<Report>(api2.report);
  return (
    <section className="panel">
      <h2>Portfolio</h2>
      <Err e={error} />
      <h3>Covenant alerts</h3>
      {data && data.breaches.length === 0 && <p>No breaches in the visible data.</p>}
      <ul className="list">
        {data?.breaches.map((b, i) => (
          <li key={i} className="alert">
            {b.company}: {b.kpi_metric} {b.period} <span className="pill bad">{b.status}</span> value {fmtAmount(b.value, b.unit ?? "")}, threshold {fmtAmount(b.threshold, b.unit ?? "")}
          </li>
        ))}
      </ul>
      {data?.companies.map((c) => (
        <div key={c.id}>
          <h3>{c.name}</h3>
          {c.kpis.length === 0 && <p>No visible KPI observations.</p>}
          <ul className="list">
            {c.kpis.map((k, i) => (
              <li key={i}>{k.metric} {k.period}: <b>{fmtAmount(k.value, k.unit)}</b>{k.sources[0] && ` (doc ${k.sources[0].document_id.slice(0, 8)}, p.${k.sources[0].page})`}</li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

const isNum = (v: unknown): v is number => typeof v === "number";

export function EvalDashboard() {
  const { data, error } = useLoad<EvalRunRow[]>(api2.evals);
  const bySuite = new Map<string, EvalRunRow[]>();
  data?.forEach((r) => bySuite.set(r.suite, [...(bySuite.get(r.suite) ?? []), r]));
  return (
    <section className="panel">
      <h2>Evals</h2>
      <Err e={error} />
      {data && data.length === 0 && <p>No eval runs recorded. Run evals/record.py to add some.</p>}
      {[...bySuite.entries()].map(([suite, runs]) => {
        const latest = runs[0];
        const numeric = Object.entries(latest.metrics).filter(([, v]) => isNum(v));
        const misses = latest.metrics["misses"];
        return (
          <div key={suite}>
            <h3>{suite}</h3>
            <p>Latest run {latest.ran_at.slice(0, 19)}{latest.note ? ` (${latest.note})` : ""}; {runs.length} run(s) recorded.</p>
            <table>
              <thead><tr><th>Metric</th><th>Latest</th><th>Previous</th></tr></thead>
              <tbody>
                {numeric.map(([k, v]) => {
                  const prev = runs[1]?.metrics[k];
                  return <tr key={k}><td>{k}</td><td className="num">{String(v)}</td><td className="num">{isNum(prev) ? String(prev) : "-"}</td></tr>;
                })}
              </tbody>
            </table>
            {Array.isArray(misses) && misses.length > 0 && (
              <details><summary>{misses.length} miss(es) in the latest run</summary>
                <pre>{JSON.stringify(misses, null, 1)}</pre></details>
            )}
          </div>
        );
      })}
    </section>
  );
}
