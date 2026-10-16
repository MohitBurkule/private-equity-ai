import { useEffect, useState } from "react";
import { api, getApiKey, setApiKey } from "./api";
import { Deals, EvalDashboard, PortfolioPanel, ReviewQueue } from "./Panels";
import { Workspace } from "./Workspace";

const TABS = ["Workspace", "Review", "Deals", "Portfolio", "Evals"] as const;

function KeyGate({ onOk, message }: { onOk: () => void; message: string }) {
  const [k, setK] = useState("");
  return (
    <div className="card gate">
      <h1>PE Platform</h1>
      <p className="mut">Paste your API key to open your fund's workspace. Admins create keys with <code>POST /admin/tenants</code> (see the runbook).</p>
      <form onSubmit={(e) => { e.preventDefault(); setApiKey(k.trim()); onOk(); }}>
        <input type="password" value={k} onChange={(e) => setK(e.target.value)} placeholder="pe_..." aria-label="API key" autoFocus />
        <button type="submit">Connect</button>
      </form>
      {message && <p role="alert" className="alert">{message}</p>}
    </div>
  );
}

export function App() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Workspace");
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
  const signOut = () => { setApiKey(""); setMsg(""); setState("need-key"); };

  if (state !== "ok") {
    return <div className="page">{state === "checking" ? <p className="mut">Connecting...</p> : <KeyGate onOk={check} message={msg} />}</div>;
  }
  return (
    <>
      <header className="topbar"><div className="topbar-in">
        <span className="brand">PE Platform</span>
        <nav className="tabs" aria-label="Sections">
          {TABS.map((t) => <button key={t} className="tab" onClick={() => setTab(t)} aria-pressed={tab === t}>{t}</button>)}
        </nav>
        <span className="keybox"><button onClick={signOut}>Sign out</button></span>
      </div></header>
      <div className="page">
        {tab === "Workspace" && <Workspace />}
        {tab === "Review" && <ReviewQueue />}
        {tab === "Deals" && <Deals />}
        {tab === "Portfolio" && <PortfolioPanel />}
        {tab === "Evals" && <EvalDashboard />}
      </div>
    </>
  );
}
