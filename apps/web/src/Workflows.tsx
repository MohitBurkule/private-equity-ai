import { Play } from "lucide-react";
import { useState } from "react";
import { AgentRunOut, api2, WorkflowInfo } from "./api";
import { useLoad } from "./hooks";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Input, Loading } from "./ui";

function Runner({ w }: { w: WorkflowInfo }) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const [run, setRun] = useState<AgentRunOut | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Card>
      <CardHead title={w.name} hint={w.description} right={<Badge>{w.steps.length} steps</Badge>} />
      <form className="flex flex-wrap items-end gap-3 p-5" onSubmit={(e) => {
        e.preventDefault(); setBusy(true); setErr(""); setRun(null);
        api2.runWorkflow(w.name, vals).then(setRun).catch((x) => setErr(String(x))).finally(() => setBusy(false));
      }}>
        {Object.entries(w.inputs).map(([k, hint]) => (
          <label key={k} className="text-xs text-mut">{k.replace("?", "")}{k.endsWith("?") && " (optional)"}
            <Input className="mt-1 block" value={vals[k] ?? ""} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} placeholder={hint} />
          </label>
        ))}
        <Button variant="primary" type="submit" disabled={busy}><Play size={14} />{busy ? "Running..." : "Run"}</Button>
      </form>
      <ErrorLine e={err} />
      {run && (
        <div className="border-t border-line p-5">
          <p className="mb-2 flex items-center gap-2 text-sm font-medium">Run {run.id} <Badge tone={run.status === "done" ? "ok" : "bad"}>{run.status}</Badge></p>
          {run.error && <p role="alert" className="mb-2 text-sm text-bad">{run.error}</p>}
          <ol className="mb-3 space-y-1 text-xs text-mut">
            {run.steps.map((s, i) => <li key={i}>{i + 1}. {s.id ?? s.tool} <span className="text-fg">({s.tool})</span> {s.error ? <span className="text-bad">{s.error}</span> : "ok"}</li>)}
          </ol>
          {run.result != null && <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-sunk p-3 font-mono text-[12px]">{JSON.stringify(run.result, null, 2)}</pre>}
        </div>
      )}
    </Card>
  );
}

export function Workflows() {
  const { data, error, loading } = useLoad(api2.workflows);
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-6">
      <div><h1 className="text-xl font-semibold tracking-tight">Workflows</h1>
        <p className="text-sm text-mut">Repeatable multi-step jobs built from the same tools the chat agent uses. Every step and its output is logged.</p></div>
      <ErrorLine e={error} />
      {loading && <Loading />}
      {data?.length === 0 && <Card><Empty>No workflows are registered on this server yet.</Empty></Card>}
      {data?.map((w) => <Runner key={w.name} w={w} />)}
    </div>
  );
}
