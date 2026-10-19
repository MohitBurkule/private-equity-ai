import { AlertTriangle, CheckCircle2, FileWarning, GitCompareArrows, ListChecks, TrendingUp } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { api, api2 } from "./api";
import { fmtAmount } from "./format";
import { Badge, Card, CardHead, Empty, ErrorLine } from "./ui";

interface Item { key: string; tone: "bad" | "warn" | "acc"; icon: ReactNode; title: string; body: string; go: string }

/** Proactive inbox: alerts computed from the user's own data every time the app opens. */
export function Inbox({ onGo }: { onGo: (tab: string) => void }) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const load = async () => {
      const out: Item[] = [];
      const day = new Date(Date.now() - 864e5).toISOString();
      // A failed source must not read as "nothing needs attention": count the failures and say so when every source failed.
      const failures: string[] = [];
      const soft = <T,>(p: Promise<T>, fallback: T) => p.catch((e: unknown) => { failures.push(String(e)); return fallback; });
      const [brief, report, conflicts, queue, deals, alerts] = await Promise.all([
        soft(api2.brief(day), null), soft(api2.report(), null), soft(api2.conflicts(), []),
        soft(Promise.all([api2.facts("auto"), api2.facts("ocr_unverified")]).then((a) => a.flat()), []),
        soft(api2.deals(), []), soft(api2.alerts("new"), []),
      ]);
      if (failures.length === 6) { setError(failures[0]); setItems(null); return; }
      if (brief && brief.total > 0) {
        const crit = brief.by_severity.critical ?? 0;
        out.push({
          key: "brief", tone: crit ? "bad" : "warn", icon: <AlertTriangle size={16} />, go: "Portfolio",
          title: `${brief.total} new alert${brief.total > 1 ? "s" : ""} in the last 24 hours`,
          body: Object.entries(brief.by_severity).map(([s, n]) => `${n} ${s}`).join(", ") + ". Mailed daily when a digest is scheduled.",
        });
      }
      report?.breaches.forEach((b, i) => out.push({
        key: `b${i}`, tone: "bad", icon: <AlertTriangle size={16} />, go: "Portfolio",
        title: `Covenant breach: ${b.company}`,
        body: `${b.kpi_metric} ${b.period} is ${fmtAmount(b.value, b.unit ?? "")} against ${fmtAmount(b.threshold, b.unit ?? "")}.`,
      }));
      // The KPI check flags a month whose move is far outside the company's own usual move. The figure stays as reported.
      alerts.filter((a) => a.kind === "kpi_anomaly").forEach((a) => out.push({
        key: `k${a.id}`, tone: "warn", icon: <TrendingUp size={16} />, go: "Portfolio",
        title: a.title, body: a.detail,
      }));
      conflicts.forEach((c, i) => out.push({
        key: `c${i}`, tone: c.likely_rounding ? "acc" : "warn", icon: <GitCompareArrows size={16} />, go: "Review",
        title: `Documents disagree: ${c.entity} ${c.metric}`,
        body: `${c.period}: values differ by ${c.spread_pct}%${c.likely_rounding ? " (likely rounding)" : ""}.`,
      }));
      if (queue.length) out.push({ key: "q", tone: "warn", icon: <FileWarning size={16} />, go: "Review",
        title: `${queue.length} extracted fact${queue.length > 1 ? "s" : ""} waiting for review`, body: "Nothing reaches a memo until an analyst accepts it." });
      deals.filter((d) => d.dd_open > 0).forEach((d) => out.push({
        key: `d${d.name}`, tone: "acc", icon: <ListChecks size={16} />, go: "Deals",
        title: `${d.name}: ${d.dd_open} of ${d.dd_total} diligence requests open`, body: `Stage: ${d.stage}. ${d.documents} document(s) uploaded.`,
      }));
      setItems(out);
    };
    void load();
  }, []);
  return (
    <Card className="flex h-full flex-col">
      <CardHead title="Inbox" hint="Things that need you, found automatically" right={items && <Badge tone={items.length ? "warn" : "ok"}>{items.length}</Badge>} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ErrorLine e={error} />
        {items === null && !error && <Empty>Checking your data...</Empty>}
        {items?.length === 0 && <Empty><CheckCircle2 className="mx-auto mb-2 text-ok" size={20} />Nothing needs attention.</Empty>}
        <ul className="divide-y divide-line">
          {items?.map((it) => (
            <li key={it.key}>
              <button onClick={() => onGo(it.go)} className="flex w-full gap-3 px-5 py-3 text-left hover:bg-sunk">
                <span className={it.tone === "bad" ? "text-bad" : it.tone === "warn" ? "text-warn" : "text-acc"}>{it.icon}</span>
                <span className="min-w-0"><span className="block text-sm font-medium">{it.title}</span><span className="block text-xs text-mut">{it.body}</span></span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}
