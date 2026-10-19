import { useEffect, useState } from "react";
import { api2, DealRow } from "./api";
import { Badge, Card, CardHead, ErrorLine, Page } from "./ui";

// Mirrors the deal stages the API accepts, in pipeline order. Passed deals stay on the board so they are not lost.
const STAGES = ["sourcing", "screening", "nda", "cim", "ioi", "loi", "dd", "ic", "signed", "closed", "passed"];

/** Deals grouped by stage. A stage can be changed from its card; the list is the same one the Deals screen reads. */
export function Pipeline() {
  const [deals, setDeals] = useState<DealRow[] | null>(null);
  const [error, setError] = useState("");

  const load = () => api2.deals().then(setDeals).catch((e: unknown) => setError(String(e)));
  useEffect(() => { void load(); }, []);

  const move = (name: string, stage: string) => {
    api2.setStage(name, stage).then(() => load()).catch((e: unknown) => setError(String(e)));
  };

  return (
    <Page title="Pipeline" hint="Deals by stage. Move a deal with its stage control; the Deals screen shows the diligence lists.">
      <Card>
        <CardHead title="Board" right={deals && <Badge tone="mut">{deals.length} deals</Badge>} />
        <ErrorLine e={error} />
        {deals?.length === 0 && <p className="px-5 py-4 text-sm text-mut">No deals yet. Create one on the Deals screen.</p>}
        <div className="flex gap-3 overflow-x-auto p-5">
          {STAGES.map((stage) => {
            const cards = deals?.filter((d) => d.stage === stage) ?? [];
            return (
              <section key={stage} aria-label={`${stage} column`} className="flex w-44 shrink-0 flex-col gap-2 rounded-lg bg-sunk p-2">
                <h3 className="flex items-center justify-between px-1 text-xs uppercase tracking-wider text-mut">
                  {stage}<span className="tnum">{cards.length}</span>
                </h3>
                {cards.map((d) => (
                  <article key={d.name} className="space-y-2 rounded-md border border-line bg-panel p-2.5 text-sm">
                    <p className="font-medium">{d.name}</p>
                    <p className="text-xs text-mut">{d.documents} docs · {d.dd_total ? `${d.dd_total - d.dd_open}/${d.dd_total} received` : "no list"}</p>
                    <select aria-label={`Move ${d.name}`} value={d.stage} onChange={(e) => move(d.name, e.target.value)}
                      className="w-full rounded-md border border-line bg-bg px-2 py-1 text-xs">
                      {STAGES.map((s) => <option key={s}>{s}</option>)}
                    </select>
                  </article>
                ))}
              </section>
            );
          })}
        </div>
      </Card>
    </Page>
  );
}
