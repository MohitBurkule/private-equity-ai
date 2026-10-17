import { useState } from "react";
import { api2, ICReview } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

const TONE = { proceed: "ok", pass: "bad", hold: "warn", more_diligence: "acc" } as const;

/** The IC record as it stands: the latest decision, the dissents on file, and filings made after that decision. */
export function IcReview() {
  const [deal, setDeal] = useState("");
  const [review, setReview] = useState<ICReview | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <Page title="IC review" hint="The record for one deal. A filing after the latest decision is a change to weigh before anyone relies on the decision.">
      <Card>
        <CardHead title="Deal" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => {
          e.preventDefault(); if (!deal.trim()) return;
          setBusy(true); setErr("");
          api2.icReview(deal.trim()).then(setReview).catch((x) => { setReview(null); setErr(String(x)); }).finally(() => setBusy(false));
        }}>
          <label className="text-xs text-mut">Deal name<Input className="mt-1" value={deal} onChange={(e) => setDeal(e.target.value)} placeholder="Deal" /></label>
          <Button variant="primary" type="submit" disabled={!deal.trim() || busy}>{busy ? "Loading" : "Load record"}</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {review && !review.ic_recorded && <Empty>No IC decision recorded for this deal.</Empty>}
      {review?.latest && (
        <>
          <Card>
            <CardHead title="Latest decision" hint={review.latest.recorded_at} />
            <div className="space-y-2 p-5 text-sm">
              <Badge tone={TONE[review.latest.outcome as keyof typeof TONE] ?? "mut"}>{review.latest.outcome.replace("_", " ")}</Badge>
              <p>{review.latest.rationale}</p>
            </div>
          </Card>
          <Card>
            <CardHead title="Changed since IC" hint={`${review.changed_since_ic.length} filed after the decision`} />
            {review.changed_since_ic.length === 0 ? (
              <p className="p-5 text-sm text-mut">Nothing filed since the decision.</p>
            ) : (
              <ul className="divide-y divide-line text-sm">
                {review.changed_since_ic.map((d) => (
                  <li key={d.document_id} className="flex justify-between gap-3 p-3">
                    <span>{d.filename}</span>
                    <span className="text-xs text-mut">{d.created_at ?? ""}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHead title="Dissents on file" hint={`${review.dissents.length} recorded`} />
            {review.dissents.length === 0 ? (
              <p className="p-5 text-sm text-mut">No dissent recorded.</p>
            ) : (
              <ul className="divide-y divide-line text-sm">
                {review.dissents.map((d) => (
                  <li key={d.id} className="space-y-1 p-3">
                    <div className="text-xs text-mut">{d.dissenter ?? "unnamed"} · {d.outcome.replace("_", " ")} · {d.recorded_at}</div>
                    <p>{d.dissent}</p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </Page>
  );
}
