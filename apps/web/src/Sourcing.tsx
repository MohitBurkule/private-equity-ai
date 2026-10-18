import { useState } from "react";
import { api2, SearchCandidate, ThesisRanked } from "./api";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

const FORMS = ["10-K", "10-Q", "8-K", "S-1", "424B4"];
// The EDGAR search needs a date window. Default to the last year so the results are recent.
const today = () => new Date().toISOString().slice(0, 10);
const yearAgo = () => new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);

const splitList = (v: string) => v.split(",").map((x) => x.trim()).filter(Boolean);
const money = (v: string) => v.trim() || null;

/** Ranks the current candidates against a firm thesis. Each met criterion cites its filing; an unmet one says why. */
function ThesisPanel({ candidates }: { candidates: SearchCandidate[] }) {
  const [sic, setSic] = useState("");
  const [keywords, setKeywords] = useState("");
  const [minRev, setMinRev] = useState("");
  const [maxRev, setMaxRev] = useState("");
  const [ranked, setRanked] = useState<ThesisRanked[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const score = async () => {
    setBusy(true); setError("");
    try {
      const out = await api2.thesisScore({
        thesis: { sic_divisions: splitList(sic), keywords: splitList(keywords), min_revenue: money(minRev), max_revenue: money(maxRev) },
        // Candidate text and revenue are not fetched here, so keyword and revenue criteria stay unmet until a filing is loaded.
        filings: candidates.filter((c) => c.source_url).map((c) => ({ url: c.source_url as string, name: c.name })),
      });
      setRanked(out.ranked);
    } catch (e) { setRanked(null); setError(String(e)); }
    setBusy(false);
  };

  return (
    <Card>
      <CardHead title="Thesis score" />
      <form className="grid gap-3 p-5 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); void score(); }}>
        <label className="text-sm"><span className="mb-1 block text-xs uppercase tracking-wider text-mut">SIC divisions</span>
          <Input aria-label="SIC divisions" value={sic} onChange={(e) => setSic(e.target.value)} placeholder="35, 62" /></label>
        <label className="text-sm"><span className="mb-1 block text-xs uppercase tracking-wider text-mut">Keywords</span>
          <Input aria-label="Keywords" value={keywords} onChange={(e) => setKeywords(e.target.value)} placeholder="software, subscription" /></label>
        <label className="text-sm"><span className="mb-1 block text-xs uppercase tracking-wider text-mut">Min revenue</span>
          <Input aria-label="Min revenue" value={minRev} onChange={(e) => setMinRev(e.target.value)} /></label>
        <label className="text-sm"><span className="mb-1 block text-xs uppercase tracking-wider text-mut">Max revenue</span>
          <Input aria-label="Max revenue" value={maxRev} onChange={(e) => setMaxRev(e.target.value)} /></label>
        <div className="sm:col-span-2"><Button variant="primary" type="submit" disabled={busy || candidates.length === 0}>{busy ? "Scoring..." : "Score candidates"}</Button></div>
      </form>
      <ErrorLine e={error} />
      {ranked && (
        <ul className="divide-y divide-line border-t border-line">
          {ranked.map((r) => (
            <li key={r.url} className="space-y-1 px-5 py-3 text-sm">
              <div className="flex flex-wrap items-center gap-3">
                <span className="min-w-0 flex-1 font-medium">{r.name}</span>
                <Badge tone={r.score >= 0.5 ? "ok" : r.score > 0 ? "warn" : "mut"}>{r.met} of {r.of} met</Badge>
              </div>
              <ul className="space-y-0.5 text-xs">
                {r.criteria.map((c) => (
                  <li key={c.criterion} className={c.met ? "text-ok" : "text-mut"}>
                    {c.met ? c.cite : `Unmet: ${c.reason}`} <span className="text-mut">({c.criterion})</span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

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
      {items && items.length > 0 && <ThesisPanel candidates={items} />}
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
