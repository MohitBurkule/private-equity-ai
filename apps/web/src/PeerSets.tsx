import { useState } from "react";
import { api2, PeerSet } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** Comps peer sets for one deal. Peers are re-read from EDGAR on refresh; any with no current revenue move to dropped with the reason. */
export function PeerSets() {
  const [deal, setDeal] = useState("");
  const [sets, setSets] = useState<PeerSet[] | null>(null);
  const [targetId, setTargetId] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    const d = deal.trim();
    if (!d) return;
    setBusy(true); setErr("");
    api2.peerSets(d).then(setSets).catch((x) => { setSets(null); setErr(String(x)); }).finally(() => setBusy(false));
  };

  const save = () => {
    const d = deal.trim(); const t = Number(targetId);
    if (!d || !name.trim() || !Number.isInteger(t)) return;
    setBusy(true); setErr("");
    api2.savePeerSet(d, t, name.trim())
      .then(() => { setName(""); return api2.peerSets(d); })
      .then(setSets)
      .catch((x) => setErr(String(x)))
      .finally(() => setBusy(false));
  };

  const refresh = (id: number) => {
    setBusy(true); setErr("");
    api2.refreshPeerSet(deal.trim(), id)
      .then((ps) => setSets((rows) => rows?.map((r) => (r.id === id ? ps : r)) ?? null))
      .catch((x) => setErr(String(x)))
      .finally(() => setBusy(false));
  };

  return (
    <Page title="Peer sets" hint="Comps peers saved for a deal. A set needs the target's SIC code and stated revenue to be saved.">
      <Card>
        <CardHead title="Deal" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => { e.preventDefault(); load(); }}>
          <label className="flex flex-col gap-1 text-xs text-mut">Deal name<Input value={deal} onChange={(e) => setDeal(e.target.value)} placeholder="Deal" /></label>
          <Button variant="primary" type="submit" disabled={!deal.trim() || busy}>{busy ? "Loading" : "Load sets"}</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {sets && (
        <Card>
          <CardHead title="Save a set" />
          <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => { e.preventDefault(); save(); }}>
            <label className="flex flex-col gap-1 text-xs text-mut">Target id<Input inputMode="numeric" value={targetId} onChange={(e) => setTargetId(e.target.value)} /></label>
            <label className="flex flex-col gap-1 text-xs text-mut">Set name<Input value={name} onChange={(e) => setName(e.target.value)} /></label>
            <Button type="submit" disabled={!deal.trim() || !name.trim() || !/^\d+$/.test(targetId) || busy}>Save set</Button>
          </form>
        </Card>
      )}
      {sets && sets.length === 0 && <Empty>No peer sets saved for this deal.</Empty>}
      {sets?.map((ps) => (
        <Card key={ps.id}>
          <CardHead title={ps.name} hint={ps.refreshed_at ? `refreshed ${ps.refreshed_at}` : "not refreshed"}
            right={<Button onClick={() => refresh(ps.id)} disabled={busy}>Refresh</Button>} />
          <ul className="divide-y divide-line text-sm">
            {ps.items.map((it) => (
              <li key={it.cik} className="flex justify-between gap-3 p-3">
                <span>{it.name}</span>
                <span className="font-mono text-xs text-mut">{it.revenue ?? "no revenue"}</span>
              </li>
            ))}
          </ul>
          {ps.dropped.length > 0 && (
            <div className="space-y-2 p-5 text-xs">
              <div className="text-mut">Dropped ({ps.dropped.length})</div>
              {ps.dropped.map((d) => (
                <div key={d.cik} className="flex items-center gap-2"><Badge tone="warn">{d.name}</Badge><span className="text-mut">{d.reason}</span></div>
              ))}
            </div>
          )}
        </Card>
      ))}
    </Page>
  );
}
