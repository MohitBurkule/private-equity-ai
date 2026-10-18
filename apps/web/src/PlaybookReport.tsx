import { useState } from "react";
import { api, PlaybookRule } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

const TONE: Record<PlaybookRule["status"], "bad" | "ok" | "mut"> = { flagged: "bad", clear: "ok", not_compared: "mut" };
const LABEL: Record<PlaybookRule["status"], string> = { flagged: "Flagged", clear: "Clear", not_compared: "Not compared" };

/** Every firm playbook rule checked against one document. A limit with no stated number is not compared, never clear. */
export function PlaybookReport() {
  const [docId, setDocId] = useState("");
  const [docType, setDocType] = useState("credit");
  const [rules, setRules] = useState<PlaybookRule[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Page title="Playbook report" hint="Each firm rule against one document: what fired, what was checked and found clear, and what could not be compared.">
      <Card>
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => {
          e.preventDefault(); if (!docId.trim()) return;
          setBusy(true); setErr("");
          api.playbookReport(docId.trim(), docType)
            .then((r) => setRules(r.rules)).catch((x) => { setRules(null); setErr(String(x)); }).finally(() => setBusy(false));
        }}>
          <label className="flex flex-col gap-1 text-xs text-mut">Document id<Input value={docId} onChange={(e) => setDocId(e.target.value)} /></label>
          <label className="flex flex-col gap-1 text-xs text-mut">Document type<Input value={docType} onChange={(e) => setDocType(e.target.value)} /></label>
          <Button variant="primary" type="submit" disabled={!docId.trim() || busy}>{busy ? "Loading" : "Run playbook"}</Button>
        </form>
      </Card>
      <ErrorLine e={err} />
      {rules && (
        <Card>
          <CardHead
            title="Playbook rules"
            hint={`${rules.filter((r) => r.status === "flagged").length} flagged · ${rules.filter((r) => r.status === "clear").length} clear · ${rules.filter((r) => r.status === "not_compared").length} not compared`}
          />
          {rules.length === 0 && <Empty>The playbook is empty.</Empty>}
          <ul className="divide-y divide-line text-sm">
            {rules.map((r) => (
              <li key={r.rule} className="flex flex-wrap items-start gap-3 px-5 py-2.5">
                <Badge tone={TONE[r.status]}>{LABEL[r.status]}</Badge>
                <span className="min-w-[10rem] font-medium">{r.term}</span>
                <span className="flex-1">
                  <span className="block text-mut">{r.text}</span>
                  <span className="block text-xs text-mut">{r.result}</span>
                </span>
                <span className="text-xs text-mut">{r.severity}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
  );
}
