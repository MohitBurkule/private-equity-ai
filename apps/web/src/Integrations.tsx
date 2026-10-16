import { useState } from "react";
import { api2 } from "./api";
import { useLoad } from "./hooks";
import { Badge, Button, Card, CardHead, ErrorLine, Input } from "./ui";

const LABEL: Record<string, string> = { email: "Email", files: "Files and drives", crm: "CRM", chat: "Chat", dataroom: "Data rooms", "market data": "Market data", people: "People" };

export function Integrations() {
  const { data, error } = useLoad(api2.connectors);
  const [open, setOpen] = useState("");
  const [token, setToken] = useState("");
  const [deal, setDeal] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const cats = [...new Set(data?.map((c) => c.category))];
  const sync = (name: string) => {
    setMsg(""); setErr("");
    api2.syncConnector(name, token, deal).then((r) => { setMsg(`Imported ${r.ingested.length} item(s).`); setToken(""); }).catch((e) => setErr(String(e)));
  };
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-6">
      <div><h1 className="text-xl font-semibold tracking-tight">Integrations</h1>
        <p className="text-sm text-mut">Pull documents and records from the tools your team already uses. Everything imported keeps its source link. Tokens are used once and never stored.</p></div>
      <ErrorLine e={error} />
      {cats.map((cat) => (
        <Card key={cat}>
          <CardHead title={LABEL[cat] ?? cat} />
          <ul className="divide-y divide-line">
            {data?.filter((c) => c.category === cat).map((c) => (
              <li key={c.name} className="px-5 py-3">
                <div className="flex items-center gap-3">
                  <span className="flex-1 text-sm font-medium">{c.label}</span>
                  <span className="text-xs text-mut">{c.auth}</span>
                  {c.status === "live" ? <Badge tone="acc">code ready</Badge> : <Badge>planned</Badge>}
                  {c.status === "live" && <Button onClick={() => { setOpen(open === c.name ? "" : c.name); setMsg(""); setErr(""); }}>Import</Button>}
                </div>
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
      <p className="text-xs text-mut">"Code ready" means the integration is written and tested against recorded responses. It has not been run with a real account yet.</p>
    </div>
  );
}
