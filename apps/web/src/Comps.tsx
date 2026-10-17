import { useState } from "react";
import { api2, CompsOut } from "./api";
import { fmtAmount } from "./format";
import { Button, Card, CardHead, Empty, ErrorLine, Input } from "./ui";

const x = (v?: string | null) => (v == null ? "-" : `${Number(v).toFixed(1)}x`);

export function Comps() {
  const [target, setTarget] = useState("");
  const [peers, setPeers] = useState("");
  const [period, setPeriod] = useState("FY24");
  const [metrics, setMetrics] = useState("revenue, ebitda");
  const [out, setOut] = useState<CompsOut | null>(null);
  const [err, setErr] = useState("");
  const ms = metrics.split(",").map((m) => m.trim()).filter(Boolean);
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-6">
      <div><h1 className="text-xl font-semibold tracking-tight">Comps and precedents</h1>
        <p className="text-sm text-mut">Multiples come from cited facts about each peer. With too few usable peers there is no range, never a guess.</p></div>
      <Card>
        <CardHead title="Build a set" />
        <form className="grid gap-3 p-5 sm:grid-cols-2" onSubmit={(e) => {
          e.preventDefault(); setErr("");
          api2.comps({ target, peers: peers.split(",").map((p) => p.trim()).filter(Boolean), period, metrics: ms }).then(setOut).catch((e2) => setErr(String(e2)));
        }}>
          <label className="text-xs text-mut">Target<Input className="mt-1 w-full" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="Target company" /></label>
          <label className="text-xs text-mut">Period<Input className="mt-1 w-full" value={period} onChange={(e) => setPeriod(e.target.value)} /></label>
          <label className="text-xs text-mut sm:col-span-2">Peers, comma separated<Input className="mt-1 w-full" value={peers} onChange={(e) => setPeers(e.target.value)} placeholder="Peer A, Peer B, Peer C" /></label>
          <label className="text-xs text-mut">Metrics<Input className="mt-1 w-full" value={metrics} onChange={(e) => setMetrics(e.target.value)} /></label>
          <div className="flex items-end"><Button variant="primary" type="submit" disabled={!target || !peers}>Run comps</Button></div>
        </form>
        <ErrorLine e={err} />
      </Card>
      {out && (
        <>
          <Card>
            <CardHead title="Implied valuation" hint={`${out.target}, ${out.period}`} />
            {out.implied.length === 0 && <Empty>No implied range. It needs at least 3 peers with a usable multiple. Check the peer rows below for the reason each one was left out.</Empty>}
            <table className="w-full text-sm"><thead><tr className="text-left text-[11px] uppercase tracking-wider text-mut">
              <th className="px-5 py-2">Basis</th><th className="text-right">Low</th><th className="text-right">Mid</th><th className="px-5 text-right">High</th></tr></thead>
              <tbody>{out.implied.map((i) => (
                <tr key={i.metric} className="border-t border-line"><td className="px-5 py-2">{i.multiple}{i.note && <span className="ml-2 text-xs text-warn">{i.note}</span>}</td>
                  {(["low", "mid", "high"] as const).map((k, n) => <td key={k} className={"tnum text-right " + (n === 2 ? "px-5" : "")}>{i[k] ? fmtAmount(i[k] as string, i.unit ?? "USD") : "-"}</td>)}</tr>
              ))}</tbody></table>
          </Card>
          <Card>
            <CardHead title="Peer multiples" />
            <table className="w-full text-sm"><thead><tr className="text-left text-[11px] uppercase tracking-wider text-mut">
              <th className="px-5 py-2">Peer</th>{ms.map((m) => <th key={m} className="px-5 text-right">EV/{m}</th>)}</tr></thead>
              <tbody>{out.peers.map((p) => (
                <tr key={p.entity} className="border-t border-line"><td className="px-5 py-2">{p.entity}</td>{ms.map((m) => <td key={m} className="tnum px-5 text-right">{x(p.multiples[m])}</td>)}</tr>
              ))}
              <tr className="border-t border-line bg-sunk text-mut"><td className="px-5 py-2">Median (n)</td>{ms.map((m) => <td key={m} className="tnum px-5 text-right">{x(out.stats[m]?.median)} ({out.stats[m]?.n ?? 0})</td>)}</tr></tbody></table>
          </Card>
        </>
      )}
    </div>
  );
}
