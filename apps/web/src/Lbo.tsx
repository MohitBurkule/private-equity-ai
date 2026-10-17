import { useState } from "react";
import { api2, FactRow, LboResult } from "./api";
import { fmtAmount } from "./format";
import { useLoad } from "./hooks";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Page } from "./ui";

// Mirrors lbo.REQUIRED on the API. Every one must be a verified, cited fact, so the picker lists only those.
const REQUIRED = ["ebitda", "entry_multiple", "exit_multiple", "leverage", "interest_rate"] as const;
const AXIS = ["8", "9", "10", "11", "12"];

/** Sponsor returns from cited inputs. The grid re-runs the model per entry/exit pair on the server. */
export function Lbo() {
  const facts = useLoad(() => api2.facts("verified"));
  const [pick, setPick] = useState<Record<string, string>>({});
  const [result, setResult] = useState<LboResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true); setError("");
    const inputs = Object.fromEntries(REQUIRED.filter((k) => pick[k]).map((k) => [k, { fact_id: Number(pick[k]) }]));
    try {
      setResult(await api2.lboReturns({ inputs, entry_multiples: AXIS, exit_multiples: AXIS }));
    } catch (e) { setResult(null); setError(String(e)); }
    setBusy(false);
  };

  const label = (f: FactRow) => `${f.entity} · ${f.metric} · ${f.period}: ${fmtAmount(f.value, f.unit)}`;
  const grid = result?.sensitivity ?? [];
  const ready = REQUIRED.every((k) => pick[k]);

  return (
    <Page title="LBO returns" hint="Every input is a verified fact with its source. An uncited input is refused, so the model never runs on a guess.">
      <Card>
        <CardHead title="Inputs" hint="Pick a verified fact for each input. Facts come from the review queue." />
        <ErrorLine e={error} />
        {facts.data?.length === 0 && <Empty>No verified facts yet. Accept facts in Review first.</Empty>}
        <div className="grid gap-3 p-5 sm:grid-cols-2">
          {REQUIRED.map((k) => (
            <label key={k} className="text-sm">
              <span className="mb-1 block text-xs uppercase tracking-wider text-mut">{k.replace(/_/g, " ")}</span>
              <select value={pick[k] ?? ""} onChange={(e) => setPick({ ...pick, [k]: e.target.value })}
                className="w-full rounded-lg border border-line bg-panel px-2.5 py-2 text-sm">
                <option value="">Choose a verified fact</option>
                {facts.data?.map((f) => <option key={f.id} value={f.id}>{label(f)}</option>)}
              </select>
            </label>
          ))}
        </div>
        <div className="flex items-center gap-3 border-t border-line px-5 py-3">
          <Button variant="primary" disabled={!ready || busy} onClick={() => void run()}>{busy ? "Running..." : "Run returns"}</Button>
          {!ready && <span className="text-xs text-mut">Pick all five inputs to run.</span>}
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
                        const cell = grid.find(([a, b]) => a === en && b === ex);
                        const m = cell?.[2] ?? null;
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
