import { useState } from "react";
import { api2, MemoVersionDiff } from "./api";
import { useLoad } from "./hooks";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Loading } from "./ui";

/**
 * Saved memo drafts for one entity, and what changed between two of them. A figure change shows both numbers
 * with the source notes on each side, so the reader can open either source. Claims that appeared or went are
 * listed as they are; nothing here is summarised away.
 */
export function MemoVersions({ entity }: { entity: string }) {
  const versions = useLoad(() => api2.memoVersions(entity).then((r) => r.items), [entity]);
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [diff, setDiff] = useState<MemoVersionDiff | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const rows = versions.data ?? [];
  const older = from ?? rows[rows.length - 2]?.id ?? null;
  const newer = to ?? rows[rows.length - 1]?.id ?? null;

  const save = () => {
    setErr(""); setBusy(true);
    api2.saveMemoVersion(entity).then(() => { setFrom(null); setTo(null); setDiff(null); versions.reload(); })
      .catch((e) => setErr(String(e))).finally(() => setBusy(false));
  };
  const compare = () => {
    if (older == null || newer == null) return;
    setErr(""); setBusy(true);
    api2.memoVersionDiff(older, newer).then(setDiff).catch((e) => setErr(String(e))).finally(() => setBusy(false));
  };

  return (
    <Card>
      <CardHead title="Memo versions" hint={`Saved drafts for ${entity}. Compare two to see which figures and claims changed.`}
        right={<Button variant="primary" disabled={busy} onClick={save}>Save current draft</Button>} />
      <ErrorLine e={versions.error || err} />
      {versions.loading && <Loading />}
      {versions.data && rows.length === 0 && <Empty>No saved drafts yet. Save the current draft to start a history.</Empty>}
      {rows.length >= 2 && (
        <form className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-3 text-sm" onSubmit={(e) => { e.preventDefault(); compare(); }}>
          <label className="flex items-center gap-1.5">From
            <select aria-label="Older version" value={older ?? ""} onChange={(e) => setFrom(Number(e.target.value))} className="rounded-lg border border-line bg-panel px-2 py-1">
              {rows.map((r) => <option key={r.id} value={r.id}>v{r.number}</option>)}
            </select></label>
          <label className="flex items-center gap-1.5">To
            <select aria-label="Newer version" value={newer ?? ""} onChange={(e) => setTo(Number(e.target.value))} className="rounded-lg border border-line bg-panel px-2 py-1">
              {rows.map((r) => <option key={r.id} value={r.id}>v{r.number}</option>)}
            </select></label>
          <Button type="submit" disabled={busy || older === newer}>Compare</Button>
        </form>
      )}
      {diff && (
        <div className="space-y-4 border-t border-line px-5 py-4 text-sm">
          <p className="text-xs text-mut">v{diff.from} to v{diff.to}</p>
          <div>
            <p className="mb-1 font-medium">Figures changed ({diff.figure_changes.length})</p>
            {diff.figure_changes.length === 0 && <p className="text-mut">No figure changed.</p>}
            <ul className="space-y-1.5">
              {diff.figure_changes.map((f, i) => (
                <li key={`${f.label}-${i}`} className="rounded-lg border border-line p-2.5">
                  <span className="font-medium">{f.label}</span>: <span className="text-mut">{f.from.join(", ") || "none"}</span> to <span>{f.to.join(", ") || "none"}</span>
                  {(f.notes_from.length > 0 || f.notes_to.length > 0) && (
                    <span className="ml-2 text-xs text-mut">sources {[...f.notes_from, ...f.notes_to].join(" ")}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
          {diff.claim_changes.added.length > 0 && (
            <div><p className="mb-1 font-medium">Claims added</p>
              <ul className="list-disc space-y-1 pl-5">{diff.claim_changes.added.map((c, i) => <li key={i}>{c}</li>)}</ul></div>
          )}
          {diff.claim_changes.removed.length > 0 && (
            <div><p className="mb-1 font-medium">Claims removed</p>
              <ul className="list-disc space-y-1 pl-5">{diff.claim_changes.removed.map((c, i) => <li key={i}>{c}</li>)}</ul></div>
          )}
          {diff.figure_changes.length === 0 && diff.claim_changes.added.length === 0 && diff.claim_changes.removed.length === 0 && (
            <Badge tone="ok">No changes between these versions</Badge>
          )}
        </div>
      )}
    </Card>
  );
}
