import { useState } from "react";
import { api2, SearchCandidate } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

const FORMS = ["10-K", "10-Q", "8-K", "S-1", "424B4"];
// The EDGAR search needs a date window. Default to the last year so the results are recent.
const today = () => new Date().toISOString().slice(0, 10);
const yearAgo = () => new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);

/** Sourcing search over live registers. Candidates are listed with the filing they came from; nothing is imported here. */
export function Sourcing() {
  const [query, setQuery] = useState("");
  const [forms, setForms] = useState<string[]>([]);
  const [register, setRegister] = useState<"edgar" | "ch">("edgar");
  const [items, setItems] = useState<SearchCandidate[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true); setError("");
    try {
      const out = register === "edgar"
        ? await api2.searchEdgar({ query, forms: forms.length ? forms : ["10-K"], since: yearAgo(), until: today(), limit: 50 })
        : await api2.searchCompaniesHouse({ query, limit: 50 });
      setItems(out.items); setTotal(out.total);
    } catch (e) { setItems(null); setError(String(e)); }
    setBusy(false);
  };

  return (
    <Page title="Sourcing" hint="Search live registers for companies. Each candidate links to the filing it came from. Add one as a target to track it.">
      <Card>
        <CardHead title="Search" />
        <form className="space-y-3 p-5" onSubmit={(e) => { e.preventDefault(); if (query.trim()) void run(); }}>
          <div className="flex flex-wrap gap-2">
            <Input className="min-w-64 flex-1" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Company name or keyword" aria-label="Search query" />
            <select value={register} onChange={(e) => setRegister(e.target.value as "edgar" | "ch")} aria-label="Register"
              className="rounded-lg border border-line bg-panel px-2.5 py-2 text-sm">
              <option value="edgar">SEC EDGAR</option>
              <option value="ch">Companies House</option>
            </select>
            <Button variant="primary" type="submit" disabled={busy || !query.trim()}>{busy ? "Searching..." : "Search"}</Button>
          </div>
          {register === "edgar" && (
            <div className="flex flex-wrap gap-1.5 text-xs">
              {FORMS.map((f) => (
                <button type="button" key={f} aria-pressed={forms.includes(f)}
                  onClick={() => setForms(forms.includes(f) ? forms.filter((x) => x !== f) : [...forms, f].slice(0, 5))}
                  className={`rounded-md border px-2 py-1 ${forms.includes(f) ? "border-acc bg-acc-soft text-acc" : "border-line text-mut"}`}>{f}</button>
              ))}
            </div>
          )}
        </form>
        <ErrorLine e={error} />
      </Card>
      {items && (
        <Card>
          <CardHead title="Candidates" right={<Badge tone="mut">{total} found</Badge>} />
          {items.length === 0 && <Empty>No candidates for that search.</Empty>}
          <ul className="divide-y divide-line">
            {items.map((c, i) => (
              <li key={`${c.name}-${i}`} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                <span className="min-w-0 flex-1 font-medium">{c.name}</span>
                {c.form && <Badge tone="mut">{c.form}</Badge>}
                {c.file_date && <span className="text-xs text-mut">{c.file_date}</span>}
                {c.already_imported && <Badge tone="ok">Already a target</Badge>}
                {c.source_url && <a href={c.source_url} target="_blank" rel="noreferrer" className="text-xs text-acc">Filing</a>}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
  );
}
