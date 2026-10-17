import { api2, CovenantStatus, FactRow } from "./api";
import { SourceChip } from "./source";
import { fmtAmount } from "./format";
import { useLoad } from "./hooks";
import { Badge, Card, CardHead, Empty, Page } from "./ui";

/** Covenant tracker: every covenant of every portfolio company, each test against its cited threshold. */
export function Covenants() {
  const { data, error } = useLoad(async () => {
    const report = await api2.report();
    const rows = await Promise.all(report.companies.map(async (c) => ({ name: c.name, status: await api2.covenants(c.id) })));
    return rows as { name: string; status: CovenantStatus }[];
  });
  // Terms read from credit agreements are stored as verified facts with no reporting period.
  const terms = useLoad(async () => (await api2.facts("verified")).filter((f) => f.period === "per agreement"));
  const tone = (s: string) => (s === "breach" || s === "unit_mismatch" ? "bad" : s === "ok" || s === "pass" ? "ok" : "mut");
  const all = data?.flatMap((r) => r.status.covenants.map((c) => ({ company: r.name, ...c }))) ?? [];
  return (
    <Page title="Covenants" hint="Each KPI is tested against a cited threshold. A breach shows the period, the value and the threshold it missed.">
      {error && <Card className="p-5 text-sm text-bad">{error}</Card>}
      {data && all.length === 0 && <Card><Empty>No covenant tests on portfolio companies yet. Add one on a company, with a cited threshold.</Empty></Card>}
      {terms.data && terms.data.length > 0 && (
        <Card>
          <CardHead title="Credit agreement terms" hint="Read from the agreement itself. Each term opens the page it was found on." />
          <ul className="divide-y divide-line">
            {terms.data.map((f: FactRow) => (
              <li key={f.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                <span className="min-w-0 flex-1">{f.metric}</span>
                <span className="tnum text-mut">{Number(f.value)}{f.unit === "%" ? "%" : f.unit ? ` ${f.unit}` : ""}</span>
                {f.sources[0] && <SourceChip docId={f.sources[0].document_id} page={f.sources[0].page} quote={f.sources[0].quote} label={f.sources[0].page > 0 ? `p.${f.sources[0].page}` : "agreement text"} />}
              </li>
            ))}
          </ul>
        </Card>
      )}
      {all.length > 0 && (
        <Card>
          <CardHead title="Tests" right={<Badge tone={data?.some((r) => r.status.breaches.length) ? "bad" : "ok"}>{data?.reduce((n, r) => n + r.status.breaches.length, 0)} breach</Badge>} />
          <ul className="divide-y divide-line">
            {all.map((c) => c.tests.map((t, i) => (
              <li key={`${c.id}-${i}`} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                <span className="min-w-0 flex-1"><span className="font-medium">{c.company}</span> · {c.kpi_metric} {c.operator} {fmtAmount(t.threshold, t.unit ?? "")} · {t.period}</span>
                <span className="tnum text-mut">{fmtAmount(t.value, t.unit ?? "")}</span>
                <Badge tone={tone(t.status)}>{t.status.replace(/_/g, " ")}</Badge>
              </li>
            )))}
          </ul>
        </Card>
      )}
    </Page>
  );
}
