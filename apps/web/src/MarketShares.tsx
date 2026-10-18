import { useState } from "react";
import { api, MarketShares as Shares } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** Competitor shares of one market, each figure over the market size, both from cited facts. Derived and labelled so. */
const money = (v: string, unit: string) => {
  const n = Number(v);
  const a = Math.abs(n);
  const s = a >= 1e9 ? `${(n / 1e9).toFixed(2)}bn` : a >= 1e6 ? `${(n / 1e6).toFixed(1)}m` : n.toLocaleString();
  return `${s} ${unit}`;
};
export function MarketShares() {
  const [market, setMarket] = useState("");
  const [metric, setMetric] = useState("revenue");
  const [period, setPeriod] = useState("");
  const [result, setResult] = useState<Shares | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const ready = market.trim() !== "" && metric.trim() !== "" && period.trim() !== "";
  return (
    <Page title="Market shares" hint="Each competitor's figure over the market size, both from visible cited facts. Shares are derived, not reported.">
      <Card>
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => {
          e.preventDefault(); if (!ready) return;
          setBusy(true); setErr("");
          api.marketShares(market.trim(), metric.trim(), period.trim())
            .then(setResult).catch((x) => { setResult(null); setErr(String(x)); }).finally(() => setBusy(false));
        }}>
          <label className="text-xs text-mut">Market (entity with the size)<Input className="mt-1" value={market} onChange={(e) => setMarket(e.target.value)} /></label>
          <label className="text-xs text-mut">Metric<Input className="mt-1" value={metric} onChange={(e) => setMetric(e.target.value)} /></label>
          <label className="text-xs text-mut">Period<Input className="mt-1" value={period} onChange={(e) => setPeriod(e.target.value)} /></label>
          <Button variant="primary" type="submit" disabled={!ready || busy}>{busy ? "Loading" : "Compute shares"}</Button>
        </form>
      </Card>
      <ErrorLine e={err} />
      {result && (
        <Card>
          <CardHead
            title={`${result.metric} · ${result.period}`}
            hint={result.market_fact ? `Market: ${result.market}, ${money(result.market_fact.value, result.market_fact.unit)} (fact ${result.market_fact.fact_id})` : `Market: ${result.market}`}
          />
          <div className="flex flex-wrap gap-1 px-5 pt-3">
            <Badge tone="mut">derived</Badge>
            {result.problems.map((p) => <Badge key={p} tone="warn">{p}</Badge>)}
          </div>
          {result.competitors.length === 0 && <Empty>No competitor figures to compare.</Empty>}
          <ul className="divide-y divide-line text-sm">
            {result.competitors.map((c) => (
              <li key={c.fact_id} className="flex flex-wrap items-center gap-3 px-5 py-2.5">
                <span className="font-medium">{c.entity}</span>
                <span className="tnum text-mut">{money(c.value, result?.market_fact?.unit ?? "")}</span>
                <span className="tnum ml-auto">{c.share_pct}%</span>
                <span className="text-xs text-mut">fact {c.fact_id}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
  );
}
