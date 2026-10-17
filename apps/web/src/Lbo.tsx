import { useState } from "react";
import { api2, FactRow, LboRequest, LboResult } from "./api";
import { fmtAmount } from "./format";
import { useLoad } from "./hooks";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

// Mirrors lbo.REQUIRED on the API. Each input is a verified cited fact, or an assumption with an owner and a reason.
const REQUIRED = ["ebitda", "entry_multiple", "exit_multiple", "leverage", "interest_rate", "tax_rate", "cash_conversion", "fees_pct", "years"] as const;
const AXIS = ["8", "9", "10", "11", "12"];

type Pick =
  | { mode: "fact"; factId: string }
  | { mode: "derived"; entity: string; period: string }
  | { mode: "assumption"; value: string; set_by: string; set_on: string; reason: string };
const EMPTY: Pick = { mode: "fact", factId: "" };

/** Sponsor returns from cited inputs. Assumptions are listed on the output and never shown as sourced. */
export function Lbo() {
  const facts = useLoad(() => api2.facts("verified"));
  const [pick, setPick] = useState<Record<string, Pick>>({});
  const [result, setResult] = useState<LboResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const current = (k: string): Pick => pick[k] ?? EMPTY;
  const set = (k: string, p: Pick) => setPick({ ...pick, [k]: p });
  const ready = REQUIRED.every((k) => {
    const p = current(k);
    if (p.mode === "fact") return p.factId !== "";
    if (p.mode === "derived") return p.entity !== "" && p.period !== "";
    return p.value !== "" && p.set_by !== "" && p.set_on !== "" && p.reason !== "";
  });

  const run = async () => {
    setBusy(true); setError("");
    const inputs: LboRequest["inputs"] = {};
    for (const k of REQUIRED) {
      const p = current(k);
      if (p.mode === "fact") inputs[k] = { fact_id: Number(p.factId) };
      else if (p.mode === "derived") inputs[k] = { derived: { formula: k, entity: p.entity, period: p.period } };
      else inputs[k] = { value: p.value, assumption: { set_by: p.set_by, set_on: p.set_on, reason: p.reason } };
    }
    try {
      setResult(await api2.lboReturns({ inputs, entry_multiples: AXIS, exit_multiples: AXIS }));
    } catch (e) { setResult(null); setError(String(e)); }
    setBusy(false);
  };

  const label = (f: FactRow) => `${f.entity} · ${f.metric} · ${f.period}: ${fmtAmount(f.value, f.unit)}`;
  const grid = result?.sensitivity ?? [];

  return (
    <Page title="LBO returns" hint="Each input is a verified fact with its source, or an assumption with who set it, when and why. Assumptions are listed on the result.">
      <Card>
        <CardHead title="Inputs" />
        <ErrorLine e={error} />
        {facts.data?.length === 0 && <Empty>No verified facts yet. Accept facts in Review first.</Empty>}
        <div className="grid gap-4 p-5 sm:grid-cols-2">
          {REQUIRED.map((k) => {
            const p = current(k);
            return (
              <div key={k} className="text-sm">
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-xs uppercase tracking-wider text-mut">{k.replace(/_/g, " ")}</span>
                  {p.mode === "fact" && k === "ebitda" && <button type="button" className="text-xs text-acc"
                    onClick={() => set(k, { mode: "derived", entity: "", period: "" })}>Derive from components</button>}
                  {p.mode !== "fact" && <button type="button" className="text-xs text-acc" onClick={() => set(k, EMPTY)}>Use a verified fact</button>}
                  {p.mode === "fact" && <button type="button" className="ml-3 text-xs text-acc"
                    onClick={() => set(k, { mode: "assumption", value: "", set_by: "", set_on: "", reason: "" })}>Use an assumption</button>}
                </div>
                {p.mode === "fact" ? (
                  <select value={p.factId} onChange={(e) => set(k, { mode: "fact", factId: e.target.value })}
                    className="w-full rounded-lg border border-line bg-panel px-2.5 py-2 text-sm">
                    <option value="">Choose a verified fact</option>
                    {facts.data?.map((f) => <option key={f.id} value={f.id}>{label(f)}</option>)}
                  </select>
                ) : p.mode === "derived" ? (
                  <div className="grid grid-cols-2 gap-1.5 rounded-lg border border-line p-2.5">
                    <Badge tone="acc">Derived: operating income + D&amp;A</Badge>
                    <span />
                    <Input placeholder="Entity, e.g. 3M Company" aria-label={`${k} entity`} value={p.entity} onChange={(e) => set(k, { ...p, entity: e.target.value })} />
                    <Input placeholder="Period, e.g. FY2019" aria-label={`${k} period`} value={p.period} onChange={(e) => set(k, { ...p, period: e.target.value })} />
                  </div>
                ) : (
                  <div className="space-y-1.5 rounded-lg border border-dashed border-warn p-2.5">
                    <Badge tone="warn">Assumption</Badge>
                    <div className="grid grid-cols-2 gap-1.5">
                      <Input placeholder="Value" aria-label={`${k} value`} value={p.value} onChange={(e) => set(k, { ...p, value: e.target.value })} />
                      <Input placeholder="Set by" aria-label={`${k} set by`} value={p.set_by} onChange={(e) => set(k, { ...p, set_by: e.target.value })} />
                      <Input type="date" aria-label={`${k} set on`} value={p.set_on} onChange={(e) => set(k, { ...p, set_on: e.target.value })} />
                      <Input placeholder="Why" aria-label={`${k} reason`} value={p.reason} onChange={(e) => set(k, { ...p, reason: e.target.value })} />
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-3 border-t border-line px-5 py-3">
          <Button variant="primary" disabled={!ready || busy} onClick={() => void run()}>{busy ? "Running..." : "Run returns"}</Button>
          {!ready && <span className="text-xs text-mut">Fill all nine inputs to run.</span>}
        </div>
      </Card>
      {result && (
        <Card>
          <CardHead title="Returns" right={<Badge tone="acc">MOIC {result.moic}x</Badge>} />
          <dl className="grid grid-cols-2 gap-4 p-5 text-sm sm:grid-cols-4">
            <div><dt className="text-xs text-mut">Equity in</dt><dd className="tnum font-medium">{fmtAmount(result.equity, "")}</dd></div>
            <div><dt className="text-xs text-mut">Exit equity</dt><dd className="tnum font-medium">{fmtAmount(result.exit_equity, "")}</dd></div>
            <div><dt className="text-xs text-mut">IRR</dt><dd className="tnum font-medium">{result.irr === null ? "n/a" : `${(Number(result.irr) * 100).toFixed(1)}%`}</dd></div>
            <div><dt className="text-xs text-mut">Debt at entry</dt><dd className="tnum font-medium">{fmtAmount(result.debt, "")}</dd></div>
          </dl>
          {result.derived.length > 0 && (
            <div className="border-t border-line px-5 py-4 text-sm">
              <p className="mb-2 text-xs uppercase tracking-wider text-mut">Derived in this result</p>
              {result.derived.map((d) => <p key={d.input}>{d.input.replace(/_/g, " ")}: {d.formula} from {d.components.length} cited facts (fact ids {d.components.join(", ")})</p>)}
            </div>
          )}
          {result.assumptions.length > 0 && (
            <div className="border-t border-dashed border-warn px-5 py-4 text-sm">
              <p className="mb-2 text-xs uppercase tracking-wider text-warn">Assumptions in this result</p>
              <ul className="space-y-1">
                {result.assumptions.map((a) => (
                  <li key={a.input}>{a.input.replace(/_/g, " ")} = {a.value}, set by {a.set_by} on {a.set_on}: <span className="text-mut">{a.reason}</span></li>
                ))}
              </ul>
            </div>
          )}
          {grid.length > 0 && (
            <div className="overflow-x-auto border-t border-line px-5 py-4">
              <p className="mb-2 text-xs uppercase tracking-wider text-mut">MOIC by entry (rows) and exit (columns) multiple</p>
              <table className="tnum w-full text-center text-sm">
                <thead><tr><th className="p-1.5 text-left text-mut">Entry \ Exit</th>{AXIS.map((x) => <th key={x} className="p-1.5 font-medium">{x}x</th>)}</tr></thead>
                <tbody>
                  {AXIS.map((en) => (
                    <tr key={en}>
                      <th className="p-1.5 text-left font-medium">{en}x</th>
                      {AXIS.map((ex) => {
                        const m = grid.find(([a, b]) => a === en && b === ex)?.[2] ?? null;
                        return <td key={ex} className="p-1.5 text-mut">{m === null ? "n/a" : <span className={Number(m) >= 2 ? "text-ok" : "text-warn"}>{m}x</span>}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </Page>
  );
}
