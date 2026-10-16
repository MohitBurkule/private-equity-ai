import { BarChart3, FileText, FlaskConical, LayoutGrid, LogOut, MessageSquare, ShieldCheck, Briefcase } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, getApiKey, setApiKey } from "./api";
import { Chat } from "./Chat";
import { Dashboards } from "./Dashboards";
import { Documents } from "./Documents";
import { Inbox } from "./Inbox";
import { Deals, EvalDashboard, PortfolioPanel, ReviewQueue } from "./Panels";
import { SourceProvider } from "./source";
import { Button, Card } from "./ui";
import clsx from "clsx";

const NAV: { id: string; icon: ReactNode }[] = [
  { id: "Home", icon: <MessageSquare size={16} /> },
  { id: "Documents", icon: <FileText size={16} /> },
  { id: "Deals", icon: <Briefcase size={16} /> },
  { id: "Portfolio", icon: <LayoutGrid size={16} /> },
  { id: "Dashboards", icon: <BarChart3 size={16} /> },
  { id: "Review", icon: <ShieldCheck size={16} /> },
  { id: "Evals", icon: <FlaskConical size={16} /> },
];

function KeyGate({ onOk, message }: { onOk: () => void; message: string }) {
  const [k, setK] = useState("");
  return (
    <div className="grid min-h-screen place-items-center p-6">
      <Card className="w-full max-w-md p-8 text-center">
        <div className="mx-auto mb-4 grid h-11 w-11 place-items-center rounded-xl bg-acc text-bg"><ShieldCheck size={22} /></div>
        <h1 className="text-xl font-semibold tracking-tight">PE Platform</h1>
        <p className="mt-2 text-sm text-mut">Paste your API key to open your fund's workspace. Admins create keys with <code>POST /admin/tenants</code> (see the runbook).</p>
        <form className="mt-5 flex gap-2" onSubmit={(e) => { e.preventDefault(); setApiKey(k.trim()); onOk(); }}>
          <input type="password" value={k} onChange={(e) => setK(e.target.value)} placeholder="pe_..." aria-label="API key" autoFocus
            className="min-w-0 flex-1 rounded-lg border border-line bg-bg px-3 py-2 text-sm" />
          <Button variant="primary" type="submit">Connect</Button>
        </form>
        {message && <p role="alert" className="mt-3 text-sm text-bad">{message}</p>}
      </Card>
    </div>
  );
}

export function App() {
  const [tab, setTab] = useState("Home");
  const [state, setState] = useState<"checking" | "need-key" | "ok">(getApiKey() ? "checking" : "need-key");
  const [msg, setMsg] = useState("");
  const check = () => {
    if (!getApiKey()) { setState("need-key"); return; }
    setState("checking");
    api.documents().then(() => { setMsg(""); setState("ok"); }).catch((e) => {
      const s = String(e);
      setMsg(s.includes("401") ? "That key was not accepted. Check it and try again." : `Cannot reach the API: ${s}`);
      setState("need-key");
    });
  };
  useEffect(check, []);
  if (state === "checking") return <p className="p-8 text-mut">Connecting...</p>;
  if (state === "need-key") return <KeyGate onOk={check} message={msg} />;
  return (
    <div className="flex h-screen">
      <nav aria-label="Sections" className="flex w-52 shrink-0 flex-col border-r border-line bg-panel p-3">
        <div className="mb-4 flex items-center gap-2 px-2 py-1"><div className="grid h-7 w-7 place-items-center rounded-lg bg-acc text-bg"><ShieldCheck size={15} /></div><span className="font-semibold tracking-tight">PE Platform</span></div>
        {NAV.map((n) => (
          <button key={n.id} onClick={() => setTab(n.id)} aria-current={tab === n.id ? "page" : undefined}
            className={clsx("mb-0.5 flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm", tab === n.id ? "bg-acc-soft font-medium text-acc" : "text-mut hover:bg-sunk hover:text-fg")}>
            {n.icon}{n.id}
          </button>
        ))}
        <button onClick={() => { setApiKey(""); check(); }} className="mt-auto flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-mut hover:bg-sunk"><LogOut size={16} />Sign out</button>
      </nav>
      <SourceProvider>
        {tab === "Home" && (
          <div className="flex h-full">
            <div className="min-w-0 flex-1"><Chat /></div>
            <div className="hidden w-80 shrink-0 p-4 xl:block"><Inbox onGo={setTab} /></div>
          </div>
        )}
        {tab === "Documents" && <Documents />}
        {tab === "Deals" && <Deals />}
        {tab === "Portfolio" && <PortfolioPanel />}
        {tab === "Dashboards" && <Dashboards />}
        {tab === "Review" && <ReviewQueue />}
        {tab === "Evals" && <EvalDashboard />}
      </SourceProvider>
    </div>
  );
}
