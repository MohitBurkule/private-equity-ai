import { useState } from "react";
import { api2, DealMeeting } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** Calendar meetings whose title names a deal. The server answers 404 for a deal the key cannot see, shown as not found. */
export function DealMeetings() {
  const [deal, setDeal] = useState("");
  const [meetings, setMeetings] = useState<DealMeeting[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <Page title="Meetings" hint="Calendar meetings that name the deal in their title, soonest first.">
      <Card>
        <CardHead title="Deal" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => {
          e.preventDefault(); if (!deal.trim()) return;
          setBusy(true); setErr("");
          api2.dealMeetings(deal.trim())
            .then((r) => setMeetings(r.meetings))
            .catch((x) => { setMeetings(null); setErr(String(x)); })
            .finally(() => setBusy(false));
        }}>
          <label className="text-xs text-mut">Deal name<Input className="mt-1" value={deal} onChange={(e) => setDeal(e.target.value)} placeholder="Deal" /></label>
          <Button variant="primary" type="submit" disabled={!deal.trim() || busy}>{busy ? "Loading" : "Load meetings"}</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {meetings && meetings.length === 0 && <Empty>No meetings name this deal.</Empty>}
      {meetings && meetings.length > 0 && (
        <Card>
          <CardHead title="Meetings" hint={`${meetings.length} found`} />
          <ul className="divide-y divide-line text-sm">
            {meetings.map((m) => (
              <li key={`${m.starts_at}-${m.title}`} className="flex flex-wrap items-center justify-between gap-3 p-3">
                <div className="min-w-0">
                  <div>{m.title}</div>
                  <div className="text-xs text-mut">{new Date(m.starts_at).toLocaleString()}</div>
                </div>
                <div className="flex items-center gap-2">
                  {m.board && <Badge tone="mut">{m.board}</Badge>}
                  {m.url && <a className="text-xs text-acc" href={m.url} target="_blank" rel="noreferrer">Open</a>}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
  );
}
