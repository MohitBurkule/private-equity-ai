import { useEffect, useState } from "react";
import { api2, PersonRow } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** Experts and contacts. A person sourced for a deal is shown only to keys that can see that deal; the server leaves the rest out. */
export function People() {
  const [q, setQ] = useState("");
  const [deal, setDeal] = useState("");
  const [people, setPeople] = useState<PersonRow[] | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ name: "", organisation: "", title: "", expertise: "", deal: "" });

  const search = (query: string, d: string) => {
    setBusy(true); setErr("");
    api2.people(query.trim(), d.trim() || undefined)
      .then((r) => setPeople(r.people))
      .catch((x) => { setPeople(null); setErr(String(x)); })
      .finally(() => setBusy(false));
  };

  useEffect(() => { search("", ""); }, []);

  const add = () => {
    if (!draft.name.trim()) return;
    setBusy(true); setErr("");
    api2.addPerson({
      name: draft.name.trim(),
      organisation: draft.organisation.trim() || undefined,
      title: draft.title.trim() || undefined,
      expertise: draft.expertise.split(",").map((t) => t.trim()).filter(Boolean),
      deal: draft.deal.trim() || undefined,
    })
      .then(() => { setDraft({ name: "", organisation: "", title: "", expertise: "", deal: "" }); search(q, deal); })
      .catch((x) => setErr(String(x)))
      .finally(() => setBusy(false));
  };

  return (
    <Page title="People" hint="Experts and contacts across deals. Someone sourced for a deal is hidden from keys that cannot see it.">
      <Card>
        <CardHead title="Search" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => { e.preventDefault(); search(q, deal); }}>
          <label className="flex flex-col gap-1 text-xs text-mut">Name, organisation, title or expertise<Input value={q} onChange={(e) => setQ(e.target.value)} /></label>
          <label className="flex flex-col gap-1 text-xs text-mut">Deal<Input value={deal} onChange={(e) => setDeal(e.target.value)} /></label>
          <Button variant="primary" type="submit" disabled={busy}>{busy ? "Searching" : "Search"}</Button>
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {people && people.length === 0 && <Empty>No one matches.</Empty>}
      {people && people.length > 0 && (
        <Card>
          <CardHead title="Directory" hint={`${people.length} shown${people.length === 100 ? ", first 100" : ""}`} />
          <ul className="divide-y divide-line text-sm">
            {people.map((p) => (
              <li key={p.id} className="space-y-1 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span>{p.name}</span>
                  {p.deal && <Badge tone="acc">{p.deal}</Badge>}
                </div>
                <div className="text-xs text-mut">{[p.title, p.organisation].filter(Boolean).join(" · ")}</div>
                {p.expertise.length > 0 && <div className="text-xs text-mut">{p.expertise.join(", ")}</div>}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card>
        <CardHead title="Add a person" />
        <form className="grid gap-3 p-5 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); add(); }}>
          <label className="flex flex-col gap-1 text-xs text-mut">Name<Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
          <label className="flex flex-col gap-1 text-xs text-mut">Organisation<Input value={draft.organisation} onChange={(e) => setDraft({ ...draft, organisation: e.target.value })} /></label>
          <label className="flex flex-col gap-1 text-xs text-mut">Title<Input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></label>
          <label className="flex flex-col gap-1 text-xs text-mut">Expertise, comma separated<Input value={draft.expertise} onChange={(e) => setDraft({ ...draft, expertise: e.target.value })} /></label>
          <label className="flex flex-col gap-1 text-xs text-mut">Deal, if sourced for one<Input value={draft.deal} onChange={(e) => setDraft({ ...draft, deal: e.target.value })} /></label>
          <div className="sm:col-span-2"><Button variant="primary" type="submit" disabled={!draft.name.trim() || busy}>Add person</Button></div>
        </form>
      </Card>
    </Page>
  );
}
