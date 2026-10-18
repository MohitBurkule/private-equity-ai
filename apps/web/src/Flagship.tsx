import { useEffect, useState } from "react";
import { api, api2, DocumentInfo, FlagshipBody, FlagshipResult, FlagshipStep } from "./api";
import { Badge, Button, Card, CardHead, ErrorLine, Input, Page } from "./ui";
import { MemoVersions } from "./MemoVersions";

// Mirrors the LBO defaults the demo run uses. Each one is a labelled assumption, never a sourced figure.
const LBO_DEFAULTS: FlagshipBody["lbo"] = {
  inputs: {
    entry_multiple: { value: "12", assumption: "illustrative entry multiple of EBITDA" },
    exit_multiple: { value: "12", assumption: "exit at entry multiple" },
    leverage: { value: "5", assumption: "illustrative leverage, x EBITDA" },
    interest_rate: { value: "0.08", assumption: "illustrative cost of debt" },
    tax_rate: { value: "0.21", assumption: "US federal statutory rate" },
    cash_conversion: { value: "0.7", assumption: "illustrative FCF / EBITDA" },
    fees_pct: { value: "0.02", assumption: "illustrative deal fees" },
    years: { value: "5", assumption: "holding period" },
  },
};
const TONE = { ok: "ok", skipped: "mut", failed: "bad" } as const;

// Acronyms and hyphenated names lose their casing under capitalize, so each step gets an explicit label.
const STEP_LABELS: Record<string, string> = {
  lbo: "LBO",
  crosscheck: "Cross-check",
};

/** One click from a 10-K to the IC memo. Each step shows its own status and reason, so a skipped or failed step is visible. */
export function Flagship() {
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [docId, setDocId] = useState("");
  const [entity, setEntity] = useState("XPO");
  const [sic, setSic] = useState("4213");
  const [cik, setCik] = useState("1166003");
  const [result, setResult] = useState<FlagshipResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.documents().then((list) => {
      setDocs(list);
      // Default to the entity's own 10-K, so the screen opens on the filing the entity name names.
      const pick = list.find((d) => d.filename.includes("10-K") && d.filename.toLowerCase().includes(entity.toLowerCase()))
        ?? list.find((d) => d.filename.includes("10-K")) ?? list[0];
      if (pick) setDocId(pick.id);
    }).catch((e) => setError(String(e)));
  }, []); // the first load picks the default entity's 10-K; later edits to the entity do not move the selection

  const run = async () => {
    setBusy(true); setError(""); setResult(null);
    const today = new Date();
    const until = today.toISOString().slice(0, 10);
    const since = new Date(today.getFullYear() - 1, today.getMonth(), today.getDate()).toISOString().slice(0, 10);
    try {
      setResult(await api2.flagship({
        document_id: docId, entity, extract: true, sic, cik, peers_pages: 1,
        precedents: { since, until, limit: 3 }, lbo: LBO_DEFAULTS,
      }));
    } catch (e) { setError(String(e)); }
    setBusy(false);
  };

  const memo = result?.steps.find((s) => s.step === "memo");
  const download = async () => {
    try {
      const url = URL.createObjectURL(await api2.memoBlob(entity));
      const a = Object.assign(document.createElement("a"), { href: url, download: `${entity}_IC_memo.pptx` });
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setError(String(e)); }
  };
  return (
    <Page title="10-K to IC memo" hint="One run: tagged figures, peers, precedents, legal red flags, LBO and the memo. Each step reports whether it ran, was skipped, or failed, and why.">
      <MemoVersions entity={entity} />
      <Card>
        <CardHead title="Run" />
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 p-5 sm:grid-cols-4">
          <label className="min-w-0 text-sm sm:col-span-2">
            <span className="mb-1 block text-xs uppercase tracking-wider text-mut">Document</span>
            <select value={docId} onChange={(e) => setDocId(e.target.value)} aria-label="Document" className="w-full rounded-lg border border-line bg-panel px-2.5 py-2 text-sm">
              {docs.length === 0 && <option value="">No documents uploaded</option>}
              {docs.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
            </select>
          </label>
          <label className="text-sm"><span className="mb-1 block text-xs uppercase tracking-wider text-mut">Entity</span>
            <Input aria-label="Entity" value={entity} onChange={(e) => setEntity(e.target.value)} /></label>
          <label className="text-sm"><span className="mb-1 block text-xs uppercase tracking-wider text-mut">SIC / CIK</span>
            <div className="flex gap-1.5"><Input aria-label="SIC" value={sic} onChange={(e) => setSic(e.target.value)} />
              <Input aria-label="CIK" value={cik} onChange={(e) => setCik(e.target.value)} /></div></label>
        </div>
        <div className="flex items-center gap-3 border-t border-line px-5 py-3">
          <Button variant="primary" disabled={!docId || busy} onClick={() => void run()}>{busy ? "Running..." : "Run 10-K to IC memo"}</Button>
          {busy && <span className="text-xs text-mut">Reads the filing, then fetches peers and precedents from EDGAR. This can take a minute.</span>}
        </div>
        <ErrorLine e={error} />
      </Card>
      {result && (
        <Card>
          <CardHead title="Steps" right={memo?.status === "ok" && <button type="button" className="text-sm text-acc" onClick={() => void download()}>Download IC memo</button>} />
          <ol className="divide-y divide-line">
            {result.steps.map((s: FlagshipStep) => (
              <li key={s.step} className="flex items-start gap-3 px-5 py-3 text-sm">
                <Badge tone={TONE[s.status]}>{s.status}</Badge>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{STEP_LABELS[s.step] ?? s.step.replace(/_/g, " ")}</p>
                  {s.reason && <p className="text-mut">{s.reason}</p>}
                </div>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </Page>
  );
}
