import { api2, AlertRow } from "./api";
import { useLoad } from "./hooks";
import { Badge, Button, Card, CardHead, Empty, ErrorLine, Loading, Page } from "./ui";

/** Candidate watch: companies the weekly search found on the firm's sectors, each to be triaged by a person. */
export function CandidateWatch() {
  const { data, error, loading, reload, setError } = useLoad(async () => (await api2.alerts()).filter((a) => a.kind === "candidate"));
  const mark = (id: number, status: string) => api2.setAlertStatus(id, status).then(reload).catch((e) => setError(String(e)));
  const open = data?.filter((a) => a.status === "new") ?? [];
  const done = data?.filter((a) => a.status !== "new") ?? [];
  const row = (a: AlertRow) => (
    <li key={a.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{a.title}</p>
        <p className="mt-0.5 text-xs text-mut">{a.detail}</p>
      </div>
      <Badge tone={a.status === "new" ? "acc" : "mut"}>{a.status}</Badge>
      {a.status === "new" && <Button onClick={() => void mark(a.id, "read")}>Mark read</Button>}
    </li>
  );
  return (
    <Page title="Candidate watch" hint="Companies the weekly search found on the firm's sectors. Each one waits for a person to review it. Revenue is not checked here.">
      <ErrorLine e={error} />
      <Card>
        <CardHead title="New" right={data && <Badge tone={open.length ? "acc" : "ok"}>{open.length}</Badge>} />
        {loading && <Loading />}
        {data && open.length === 0 && <Empty>No new candidates.</Empty>}
        <ul className="divide-y divide-line">{open.map(row)}</ul>
      </Card>
      {done.length > 0 && (
        <Card>
          <CardHead title="Read or dismissed" />
          <ul className="divide-y divide-line">{done.map(row)}</ul>
        </Card>
      )}
    </Page>
  );
}
