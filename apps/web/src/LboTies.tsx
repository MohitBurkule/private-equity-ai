import { useState } from "react";
import { api2, LboTiesOut } from "./api";
import { Badge, Button, Card, CardHead, ErrorLine, Input, Page } from "./ui";

const TONE = { tied: "ok", untied: "warn", no_value: "bad" } as const;

/** Each named input of an LBO workbook against the verified facts. An untied input is flagged, never changed. */
export function LboTies() {
  const [file, setFile] = useState<File | null>(null);
  const [out, setOut] = useState<LboTiesOut | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <Page title="LBO workbook ties" hint="Each named input is checked against verified facts with the same concept and value. Assumptions such as multiples will show untied.">
      <Card>
        <CardHead title="Workbook" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => {
          e.preventDefault(); if (!file) return;
          setBusy(true); setErr("");
          api2.lboWorkbookTies(file).then(setOut).catch((x) => setErr(String(x))).finally(() => setBusy(false));
        }}>
          <label className="text-xs text-mut">Excel model<Input type="file" accept=".xlsx" className="mt-1" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
          <Button variant="primary" type="submit" disabled={!file || busy}>{busy ? "Checking" : "Check ties"}</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {out && (
        <Card>
          <CardHead title="Named inputs" hint={out.untied.length ? `${out.untied.length} untied` : "all tied"} />
          <table className="w-full text-sm">
            <thead><tr className="text-left text-xs text-mut"><th className="p-3">Name</th><th>Cell</th><th>Value</th><th>Tie</th><th>Facts</th></tr></thead>
            <tbody>{Object.entries(out.inputs).map(([name, r]) => (
              <tr key={name} className="border-t border-line">
                <td className="p-3">{name}</td>
                <td>{r.cell ?? "-"}</td>
                <td>{r.value ?? r.reason ?? "-"}</td>
                <td><Badge tone={TONE[r.tie]}>{r.tie.replace("_", " ")}</Badge></td>
                <td className="text-xs text-mut">{r.fact_ids.join(", ") || "-"}</td>
              </tr>))}</tbody>
          </table>
          {out.lbo_missing.length > 0 && (
            <p className="p-5 pt-0 text-sm text-mut">Required LBO inputs not in the workbook: {out.lbo_missing.join(", ")}</p>
          )}
        </Card>
      )}
    </Page>
  );
}
