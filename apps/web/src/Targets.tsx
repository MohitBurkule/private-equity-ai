import { useMemo, useState } from "react";
import { api2, ScreenBody, ScreenOut, Target, TargetFilter } from "./api";
import { fmtAmount } from "./format";
import { useLoad } from "./hooks";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input } from "./ui";

const W = 720, H = 360;
const PALETTE = ["#0f9d8a", "#c2410c", "#4f6bd8", "#a21caf", "#b45309", "#0369a1", "#be123c", "#4d7c0f"];

/** Dots on a plain lat/lng grid fitted to the data (no map tiles, so it works offline). Size follows revenue, colour follows sector. */
function MapView({ items, sel, onPick }: { items: Target[]; sel: number | null; onPick: (id: number) => void }) {
  const sectors = useMemo(() => [...new Set(items.map((t) => t.sector ?? "Unknown"))], [items]);
  const placed = items.filter((t) => t.lat && t.lng);
  // Fit the view to the dots so a cluster in one region is not squashed into a corner.
  const pad = (a: number[], min: number) => { const lo = Math.min(...a), hi = Math.max(...a), p = Math.max((hi - lo) * 0.15, min); return [lo - p, hi + p]; };
  const [l0, l1] = placed.length ? pad(placed.map((t) => Number(t.lng)), 5) : [-180, 180];
  const [a0, a1] = placed.length ? pad(placed.map((t) => Number(t.lat)), 5) : [-90, 90];
  const x = (lng: number) => ((lng - l0) / (l1 - l0)) * W;
  const y = (lat: number) => ((a1 - lat) / (a1 - a0)) * H;
  const maxRev = Math.max(1, ...placed.map((t) => Number(t.revenue ?? 0)));
  return (
    <div className="relative">
      {placed.length === 0 && (
        <p className="absolute inset-x-0 top-1/2 px-6 text-center text-sm text-mut">No targets have a location yet. The SEC import carries none, so the list below is the only view.</p>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Targets by location" className="w-full rounded-lg bg-sunk">
        {[0, 1, 2, 3, 4].map((i) => <line key={`v${i}`} x1={(W * i) / 4} x2={(W * i) / 4} y1={0} y2={H} stroke="var(--c-line)" />)}
        {[0, 1, 2, 3].map((i) => <line key={`h${i}`} y1={(H * i) / 3} y2={(H * i) / 3} x1={0} x2={W} stroke="var(--c-line)" />)}
        {placed.map((t) => {
          const r = t.revenue ? 4 + 10 * Math.sqrt(Number(t.revenue) / maxRev) : 3;
          const c = PALETTE[sectors.indexOf(t.sector ?? "Unknown") % PALETTE.length];
          return <circle key={t.id} cx={x(Number(t.lng))} cy={y(Number(t.lat))} r={r} fill={c} fillOpacity={0.65}
            stroke={t.id === sel ? "var(--c-fg)" : c} strokeWidth={t.id === sel ? 2 : 1} cursor="pointer" onClick={() => onPick(t.id)}>
            <title>{t.name}</title></circle>;
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-3 text-xs text-mut">
        {sectors.map((s, i) => <span key={s} className="flex items-center gap-1"><i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />{s}</span>)}
        {items.length > placed.length && <span>{items.length - placed.length} with no location are listed below only</span>}
      </div>
    </div>
  );
}

/** Screen with firm-set weights. A weight left blank is not sent, so the accepted firm weight rule (or 1) applies. */
function ScreenPanel() {
  const [sectors, setSectors] = useState("");
  const [countries, setCountries] = useState("");
  const [minRev, setMinRev] = useState("");
  const [w, setW] = useState<Record<string, string>>({ sector: "", country: "", revenue: "" });
  const [out, setOut] = useState<ScreenOut | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setErr("");
    const weights: Record<string, number> = {};
    Object.entries(w).forEach(([k, v]) => v !== "" && (weights[k] = Number(v)));
    const body: ScreenBody = {
      sectors: sectors.split(",").map((x) => x.trim()).filter(Boolean),
      countries: countries.split(",").map((x) => x.trim()).filter(Boolean),
      min_revenue: minRev || undefined,
      weights: Object.keys(weights).length ? weights : undefined,
    };
    try { setOut(await api2.screen(body)); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const wIn = (k: string, label: string) => (
    <label className="flex items-center gap-1 text-xs text-mut">{label}
      <Input aria-label={`Weight ${k}`} type="number" min={0} max={10} step="0.5" placeholder="rule" value={w[k]}
        onChange={(e) => setW({ ...w, [k]: e.target.value })} className="w-16" /></label>
  );
  return (
    <Card className="lg:col-span-2">
      <CardHead title="Screen" hint="Score = weighted share of tests passing. Unknown counts as not passed." />
      <div className="space-y-3 p-4 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <Input aria-label="Screen sectors" placeholder="Sectors, comma separated" value={sectors} onChange={(e) => setSectors(e.target.value)} className="w-56" />
          <Input aria-label="Screen countries" placeholder="Countries, comma separated" value={countries} onChange={(e) => setCountries(e.target.value)} className="w-56" />
          <Input aria-label="Screen minimum revenue" type="number" placeholder="Min revenue" value={minRev} onChange={(e) => setMinRev(e.target.value)} className="w-36" />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-mut">Weights:</span>
          {wIn("sector", "sector")}{wIn("country", "country")}{wIn("revenue", "revenue")}
          <Button variant="primary" onClick={run} disabled={busy}>{busy ? "Running" : "Run screen"}</Button>
        </div>
        <ErrorLine e={err} />
        {out && (
          <>
            <p className="text-mut">
              {out.matches} match, {out.review} to review.{" "}
              {out.applied.weights_source ? <>Weights from firm rule: <span className="text-fg">{out.applied.weights_source.value}</span>.</> : null}
            </p>
            <table className="w-full text-sm"><thead className="text-left text-xs text-mut"><tr><th className="py-2">Name</th><th>Verdict</th><th className="text-right">Score</th></tr></thead>
              <tbody>{out.items.slice(0, 50).map((t) => (
                <tr key={t.id} className="border-t border-line"><td className="py-2">{t.name}</td>
                  <td><Badge tone={t.verdict === "match" ? "ok" : "warn"}>{t.verdict}</Badge></td>
                  <td className="tnum text-right">{t.score ?? "-"}</td></tr>))}</tbody></table>
          </>
        )}
      </div>
    </Card>
  );
}

export function Targets() {
  const [f, setF] = useState<TargetFilter>({});
  const [sel, setSel] = useState<number | null>(null);
  const facets = useLoad(api2.targetFacets, []);
  const list = useLoad(() => api2.targets(f), [JSON.stringify(f)]);
  const set = (k: keyof TargetFilter, v: string) => { setF({ ...f, [k]: v || undefined }); setSel(null); };
  const items = list.data?.items ?? [];
  const cur = items.find((t) => t.id === sel);
  const bench = useLoad(() => (cur?.sector ? api2.targetBenchmark(cur.id, cur.sector) : Promise.resolve(null)), [cur?.id]);
  const selCls = "rounded-lg border border-line bg-bg px-2 py-1.5 text-sm";
  return (
    <div className="h-full overflow-y-auto p-6">
      <h1 className="mb-1 text-xl font-semibold tracking-tight">Acquisition targets</h1>
      <p className="mb-4 max-w-prose text-sm text-mut">Filter by sector, country and revenue. Revenue filters leave out targets whose revenue is unknown{facets.data ? ` (${facets.data.revenue_unknown} of ${facets.data.total})` : ""}; unknown is never treated as zero.</p>
      <ErrorLine e={list.error || facets.error} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input aria-label="Search name" placeholder="Search name" value={f.q ?? ""} onChange={(e) => set("q", e.target.value)} className="w-44" />
        <select aria-label="Sector" className={selCls} value={f.sector ?? ""} onChange={(e) => set("sector", e.target.value)}>
          <option value="">All sectors</option>{facets.data?.sector.filter((s) => s.value).map((s) => <option key={s.value} value={s.value!}>{s.value} ({s.count})</option>)}</select>
        <select aria-label="Country" className={selCls} value={f.country ?? ""} onChange={(e) => set("country", e.target.value)}>
          <option value="">All countries</option>{facets.data?.country.filter((s) => s.value).map((s) => <option key={s.value} value={s.value!}>{s.value} ({s.count})</option>)}</select>
        <Input aria-label="Min revenue" type="number" placeholder="Min revenue" value={f.min_revenue ?? ""} onChange={(e) => set("min_revenue", e.target.value)} className="w-36" />
        <Input aria-label="Max revenue" type="number" placeholder="Max revenue" value={f.max_revenue ?? ""} onChange={(e) => set("max_revenue", e.target.value)} className="w-36" />
        <span className="text-sm text-mut">{list.data ? `${list.data.total} shown` : ""}</span>
      </div>
      {items.length === 0 && list.data ? <Empty>No targets match. Import from SEC or Companies House, or loosen the filters.</Empty> : (
        <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
          <Card><CardHead title="Map" hint="Dot size = revenue. Click a dot for details." /><div className="p-4"><MapView items={items} sel={sel} onPick={setSel} /></div></Card>
          <Card>
            <CardHead title={cur ? cur.name : "Details"} />
            <div className="p-4 text-sm">
              {cur ? (
                <dl className="grid grid-cols-[6rem_1fr] gap-y-1.5">
                  <dt className="text-mut">Sector</dt><dd>{cur.sector ?? "unknown"}</dd>
                  <dt className="text-mut">Country</dt><dd>{cur.country ?? "unknown"}</dd>
                  <dt className="text-mut">Revenue</dt><dd className="tnum">{cur.revenue ? `${fmtAmount(cur.revenue, cur.currency ?? "")} ${cur.revenue_period ?? ""}` : "unknown"}
                    {cur.revenue_url && <a className="ml-2 text-acc underline" href={cur.revenue_url} target="_blank" rel="noreferrer">source</a>}</dd>
                  <dt className="text-mut">Found in</dt><dd>{cur.source} {cur.source_url ? <a className="text-acc underline" href={cur.source_url} target="_blank" rel="noreferrer">{cur.source_ref}</a> : cur.source_ref}</dd>
                  <dt className="text-mut">Status</dt><dd><Badge>{cur.status}</Badge></dd>
                </dl>
              ) : <p className="text-mut">Pick a dot or a row.</p>}
              {cur && bench.data && (
                <p className="mt-4 border-t border-line pt-3 text-mut">
                  {bench.data.peers > 0 && bench.data.median
                    ? <>Sector median revenue {fmtAmount(bench.data.median, cur.currency ?? "")} across {bench.data.peers} {bench.data.peers === 1 ? "target" : "targets"}{bench.data.target && bench.data.peers >= 3 ? <>; this one sits at the {bench.data.target.percentile}th percentile</> : bench.data.peers < 3 ? "; too few targets in this sector for a percentile" : ""}.</>
                    : "No sector revenue to compare with yet."}
                  {bench.data.excluded_no_revenue > 0 && <> {bench.data.excluded_no_revenue} without revenue are left out.</>}
                </p>
              )}
            </div>
          </Card>
          <ScreenPanel />
          <Card className="lg:col-span-2">
            <CardHead title="Targets" />
            <table className="w-full text-sm"><thead className="text-left text-xs text-mut"><tr><th className="px-4 py-2">Name</th><th>Sector</th><th>Country</th><th className="pr-4 text-right">Revenue</th></tr></thead>
              <tbody>{items.slice(0, 200).map((t) => (
                <tr key={t.id} onClick={() => setSel(t.id)} className={"cursor-pointer border-t border-line hover:bg-sunk " + (t.id === sel ? "bg-acc-soft" : "")}>
                  <td className="px-4 py-2">{t.name}</td><td>{t.sector ?? "-"}</td><td>{t.country ?? "-"}</td>
                  <td className="tnum pr-4 text-right">{t.revenue ? fmtAmount(t.revenue, t.currency ?? "") : "unknown"}</td></tr>))}</tbody></table>
          </Card>
        </div>
      )}
    </div>
  );
}
