import { useState } from "react";
import { api2, LpReport as Report } from "./api";
import { Button, Card, CardHead, Empty, ErrorLine, Input, Page } from "./ui";

/** The portfolio section for LP reporting. Each paragraph cites its sources by number; the sources are listed under it with their documents. */
export function LpReport() {
  const [period, setPeriod] = useState("");
  const [prior, setPrior] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    if (!period.trim() || !prior.trim()) return;
    setBusy(true); setErr("");
    api2.lpReport(period.trim(), prior.trim())
      .then(setReport)
      .catch((x) => { setReport(null); setErr(String(x)); })
      .finally(() => setBusy(false));
  };

  const download = (format: "docx" | "pptx") => {
    setErr("");
    api2.lpReportBlob(period.trim(), prior.trim(), format)
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = Object.assign(document.createElement("a"), { href: url, download: `portfolio-lp-report.${format}` });
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch((x) => setErr(String(x)));
  };

  return (
    <Page title="LP report" hint="Each company's cited actuals, budget against actual and change in value. A number in the text points to its source below.">
      <Card>
        <CardHead title="Periods" />
        <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => { e.preventDefault(); load(); }}>
          <label className="flex flex-col gap-1 text-xs text-mut">Period<Input value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="2026-09" /></label>
          <label className="flex flex-col gap-1 text-xs text-mut">Prior period<Input value={prior} onChange={(e) => setPrior(e.target.value)} placeholder="2026-08" /></label>
          <Button variant="primary" type="submit" disabled={!period.trim() || !prior.trim() || busy}>{busy ? "Loading" : "Build report"}</Button>
          {report && <>
            <Button onClick={() => download("docx")}>Download .docx</Button>
            <Button onClick={() => download("pptx")}>Download .pptx</Button>
          </>}
        </form>
      </Card>
      {err && <ErrorLine e={err} />}
      {report && report.paragraphs.length === 0 && <Empty>Nothing to report for these periods.</Empty>}
      {report && report.paragraphs.length > 0 && (
        <>
          <Card>
            <CardHead title={report.title} />
            <div className="space-y-3 p-5 text-sm">
              {report.paragraphs.map((para, i) => (
                <p key={i}>{para.map((part, j) => (
                  <span key={j}>{part.text}{part.source != null && <sup className="ml-0.5 text-acc">[{part.source}]</sup>} </span>
                ))}</p>
              ))}
            </div>
          </Card>
          <Card>
            <CardHead title="Sources" hint={`${report.sources.length} cited`} />
            <ol className="divide-y divide-line text-sm">
              {report.sources.map((s) => (
                <li key={s.n} className="flex flex-wrap items-center justify-between gap-2 p-3">
                  <span><span className="text-acc">[{s.n}]</span> <span className="font-mono text-xs">{s.value}</span></span>
                  {s.url
                    ? <a className="text-xs text-acc" href={s.url} target="_blank" rel="noreferrer">{s.source}</a>
                    : <span className="text-xs text-mut">{s.source}</span>}
                </li>
              ))}
            </ol>
          </Card>
        </>
      )}
    </Page>
  );
}
