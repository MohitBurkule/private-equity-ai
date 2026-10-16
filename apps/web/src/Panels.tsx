import { useEffect, useState } from "react";
import { api2, DDRow, DealRow, FactRow, Report, STAGES } from "./api";

function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const reload = () => { setError(""); load().then(setData).catch((e) => setError(String(e))); };
  useEffect(reload, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, reload, setError };
}

const Err = ({ e }: { e: string }) => (e ? <p role="alert" style={{ color: "crimson" }}>{e}</p> : null);

export function ReviewQueue() {
  const { data, error, reload, setError } = useLoad<FactRow[]>(async () => [
    ...(await api2.facts("auto")), ...(await api2.facts("ocr_unverified")),
  ]);
  const act = (id: number, action: "accept" | "reject") =>
    api2.review(id, action).then(reload).catch((e) => setError(String(e)));
  return (
    <section>
      <h2>Review queue</h2>
      <Err e={error} />
      {data && data.length === 0 && <p>Nothing waiting for review.</p>}
      <ul>
        {data?.map((f) => (
          <li key={f.id}>
            <b>{f.entity} {f.metric} {f.period}</b>: {f.value} {f.unit} [{f.status}]
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
    <section>
      <h2>Deals</h2>
      <Err e={deals.error || dd.error} />
      <form onSubmit={(e) => { e.preventDefault(); api2.createDeal(name).then(() => { setName(""); deals.reload(); }).catch(fail); }}>
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
          <ul>
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
    <section>
      <h2>Portfolio</h2>
      <Err e={error} />
      <h3>Covenant alerts</h3>
      {data && data.breaches.length === 0 && <p>No breaches in the visible data.</p>}
      <ul>
        {data?.breaches.map((b, i) => (
          <li key={i} style={{ color: "crimson" }}>
            {b.company}: {b.kpi_metric} {b.period} {b.status} (value {b.value}, threshold {b.threshold})
          </li>
        ))}
      </ul>
      {data?.companies.map((c) => (
        <div key={c.id}>
          <h3>{c.name}</h3>
          {c.kpis.length === 0 && <p>No visible KPI observations.</p>}
          <ul>
            {c.kpis.map((k, i) => (
              <li key={i}>{k.metric} {k.period}: {k.value} {k.unit}{k.sources[0] && ` (doc ${k.sources[0].document_id.slice(0, 8)}, p.${k.sources[0].page})`}</li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
