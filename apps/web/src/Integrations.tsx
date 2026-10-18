import { useState } from "react";
import { api2, type ConnectorState } from "./api";
import { useLoad } from "./hooks";
import { Badge, Button, Card, CardHead, ErrorLine, Input, Loading } from "./ui";
import { healthView } from "./integrationHealth";

const STATE: Record<ConnectorState, { label: string; tone: "ok" | "warn" | "mut" }> = {
  connected: { label: "Connected", tone: "ok" },
  needs_key: { label: "Needs key", tone: "warn" },
  stubbed: { label: "Stubbed", tone: "mut" },
};

const LABEL: Record<string, string> = { email: "Email", files: "Files and drives", crm: "CRM", chat: "Chat", dataroom: "Data rooms", "market data": "Market data", people: "People" };

export function Integrations() {
  const { data, error, loading } = useLoad(api2.connectors);
  const [open, setOpen] = useState("");
  const [token, setToken] = useState("");
  const [deal, setDeal] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const cats = [...new Set(data?.map((c) => c.category))];
  const counts = (["connected", "needs_key", "stubbed"] as const).map((st) => `${data?.filter((c) => c.state === st).length ?? 0} ${STATE[st].label.toLowerCase()}`);
  const sync = (name: string) => {
    setMsg(""); setErr("");
    api2.syncConnector(name, token, deal).then((r) => { setMsg(`Imported ${r.ingested.length} item(s).`); setToken(""); }).catch((e) => setErr(String(e)));
  };
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-6">
      <div><h1 className="text-xl font-semibold tracking-tight">Integrations</h1>
        <p className="text-sm text-mut">Pull documents and records from the tools your team already uses. Everything imported keeps its source link. Tokens are used once and never stored.</p></div>
      <ErrorLine e={error} />
      {loading && <Loading />}
      {data && <p className="text-sm text-mut">{counts.join(" · ")}</p>}
      {cats.map((cat) => (
        <Card key={cat}>
          <CardHead title={LABEL[cat] ?? cat} />
          <ul className="divide-y divide-line">
            {data?.filter((c) => c.category === cat).map((c) => (
              <li key={c.name} className="px-5 py-3">
                <div className="flex items-center gap-3">
                  <span className="flex-1 text-sm font-medium">{c.label}</span>
                  <span className="hidden text-xs text-mut sm:inline">{c.auth}</span>
                  <Badge tone={STATE[c.state].tone}>{STATE[c.state].label}</Badge>
                  {c.status === "live" && <Button onClick={() => { setOpen(open === c.name ? "" : c.name); setMsg(""); setErr(""); }}>Import</Button>}
                </div>
                <p className="mt-1 text-xs text-mut">{c.detail}</p>
                {healthView(c) && (() => {
                  const h = healthView(c)!;
                  return (
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                      <Badge tone={h.tone}>{h.label}</Badge>
                      <span className={h.tone === "warn" ? "text-bad" : "text-mut"}>{h.message}</span>
                      {h.reconnect && <Button onClick={() => { setOpen(c.name); setMsg(""); setErr(""); }}>Reconnect</Button>}
                    </div>
                  );
                })()}
                {open === c.name && (
                  <form className="mt-3 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); sync(c.name); }}>
                    <Input className="min-w-64 flex-1" type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Access token" aria-label={`${c.label} access token`} />
                    <Input value={deal} onChange={(e) => setDeal(e.target.value)} placeholder="Deal (optional)" aria-label="Deal" />
                    <Button variant="primary" type="submit" disabled={!token}>Import now</Button>
                    {msg && <p className="w-full text-sm text-ok">{msg}</p>}
                    {err && <p role="alert" className="w-full text-sm text-bad">{err}</p>}
                  </form>
                )}
              </li>
            ))}
          </ul>
        </Card>
      ))}
      <p className="text-xs text-mut">Connected means a saved connection exists, or no key is needed. Needs key means it is built but this deployment or tenant has no credentials yet. Stubbed means it is not built. Built integrations are tested against recorded responses and have not been run with a real account yet.</p>
    </div>
  );
}
