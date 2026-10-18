import { api2 } from "./api";
import { useLoad } from "./hooks";
import { SourceChip } from "./source";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Loading } from "./ui";

/** What the firm has told us about how it works: board cadence, sign-off thresholds, screening criteria, LP tone... */
export function Firm() {
  const firm = useLoad(api2.firm);
  const terms = useLoad(api2.firmTerms);
  const act = (id: number, status: string) => api2.firmReview(id, status).then(firm.reload).catch((e) => firm.setError(String(e)));
  const groups = [...new Set(terms.data?.map((t) => t.group))];
  const cov = firm.data?.coverage;
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-6">
      <div><h1 className="text-xl font-semibold tracking-tight">Firm profile</h1>
        <p className="text-sm text-mut">The rules your firm actually runs by, found in your own documents. Each value links to the quote it came from and waits for an analyst to accept it.</p></div>
      <ErrorLine e={firm.error || terms.error} />
      {cov && <Card className="p-5"><div className="mb-2 flex items-center justify-between text-sm"><span className="font-medium">Coverage</span><span className="tnum text-mut">{cov.known} of {cov.total} terms known</span></div>
        <div className="h-2 overflow-hidden rounded-full bg-sunk"><div className="h-full bg-acc" style={{ width: `${(100 * cov.known) / Math.max(cov.total, 1)}%` }} /></div></Card>}
      {groups.map((g) => (
        <Card key={g}>
          <CardHead title={g.charAt(0).toUpperCase() + g.slice(1)} />
          <ul className="divide-y divide-line">
            {terms.data?.filter((t) => t.group === g).map((t) => {
              const rows = firm.data?.profile[t.key] ?? [];
              return (
                <li key={t.key} className="px-5 py-3">
                  <p className="text-sm font-medium">{t.label}</p>
                  <p className="text-xs text-mut">{t.hint}</p>
                  {rows.length === 0 && <p className="mt-1 text-xs text-mut">Not found in your documents yet.</p>}
                  {rows.map((r) => (
                    <div key={r.id} className="mt-1.5 flex flex-wrap items-center gap-2 text-sm">
                      <span>{r.value}</span><Badge tone={r.status === "accepted" ? "ok" : "warn"}>{r.status}</Badge>
                      <SourceChip docId={r.source.document_id} page={r.source.page} quote={r.source.quote} />
                      {r.status === "pending" && <><Button variant="primary" onClick={() => void act(r.id, "accepted")}>Accept</Button><Button onClick={() => void act(r.id, "rejected")}>Reject</Button></>}
                    </div>
                  ))}
                </li>
              );
            })}
          </ul>
        </Card>
      ))}
      {terms.loading && <Loading />}
      {terms.data?.length === 0 && <Card><Empty>No terms defined.</Empty></Card>}
    </div>
  );
}
