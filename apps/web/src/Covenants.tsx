import { api2, CovenantStatus } from "./api";
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
  const tone = (s: string) => (s === "breach" || s === "unit_mismatch" ? "bad" : s === "ok" || s === "pass" ? "ok" : "mut");
  const all = data?.flatMap((r) => r.status.covenants.map((c) => ({ company: r.name, ...c }))) ?? [];
  return (
    <Page title="Covenants" hint="Each KPI is tested against a cited threshold. A breach shows the period, the value and the threshold it missed.">
      {error && <Card className="p-5 text-sm text-bad">{error}</Card>}
      {data && all.length === 0 && <Card><Empty>No covenants yet. Add one on a portfolio company.</Empty></Card>}
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
