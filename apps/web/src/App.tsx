import { Calendar, Users, Mail, BarChart3, Building2, Calculator, Workflow, FileText, Plug, FlaskConical, LayoutGrid, LogOut, MessageSquare, ShieldCheck, Briefcase, Map } from "lucide-react";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, api2, DealRow, getApiKey, setApiKey } from "./api";
import { CommandPalette } from "./CommandPalette";
import { Chat } from "./Chat";
import { Dashboards } from "./Dashboards";
import { Targets } from "./Targets";
import { Comps } from "./Comps";
import { Documents } from "./Documents";
import { Firm } from "./Firm";
import { Workflows } from "./Workflows";
import { Integrations } from "./Integrations";
import { Inbox } from "./Inbox";
import { Deals, EvalDashboard, PortfolioPanel, ReviewQueue } from "./Panels";
import { Lbo } from "./Lbo";
import { Qoe } from "./Qoe";
import { DDQa } from "./DDQa";
import { LboTies } from "./LboTies";
import { MnpiWall } from "./MnpiWall";
import { IcReview } from "./IcReview";
import { Flagship } from "./Flagship";
import { Covenants } from "./Covenants";
import { Sourcing } from "./Sourcing";
import { CandidateWatch } from "./CandidateWatch";
import { EmailReview } from "./EmailReview";
import { DealMeetings } from "./DealMeetings";
import { PeerSets } from "./PeerSets";
import { People } from "./People";
import { ResearchDeck } from "./ResearchDeck";
import { DocumentAccess } from "./DocumentAccess";
import { ValuationRounds } from "./ValuationRounds";
import { AccessReport } from "./AccessReport";
import { MarketShares } from "./MarketShares";
import { PlaybookReport } from "./PlaybookReport";
import { BudgetVsActual } from "./BudgetVsActual";
import { RollForward } from "./RollForward";
import { LpReport } from "./LpReport";
import { SourceProvider } from "./source";
import { Button, Card } from "./ui";
import clsx from "clsx";

const NAV: { id: string; icon: ReactNode }[] = [
  { id: "Home", icon: <MessageSquare size={16} /> },
  { id: "Documents", icon: <FileText size={16} /> },
  { id: "Deals", icon: <Briefcase size={16} /> },
  { id: "Portfolio", icon: <LayoutGrid size={16} /> },
  { id: "Covenants", icon: <ShieldCheck size={16} /> },
  { id: "Memo", icon: <FileText size={16} /> },
  { id: "LBO", icon: <Calculator size={16} /> },
  { id: "QoE", icon: <Calculator size={16} /> },
  { id: "DD Q&A", icon: <FileText size={16} /> },
  { id: "LBO ties", icon: <Calculator size={16} /> },
  { id: "MNPI wall", icon: <ShieldCheck size={16} /> },
  { id: "IC review", icon: <Briefcase size={16} /> },
  { id: "Email review", icon: <Mail size={16} /> },
  { id: "Meetings", icon: <Calendar size={16} /> },
  { id: "Peer sets", icon: <Calculator size={16} /> },
  { id: "People", icon: <Users size={16} /> },
  { id: "Research deck", icon: <FileText size={16} /> },
  { id: "Document access", icon: <ShieldCheck size={16} /> },
  { id: "Valuation history", icon: <Calculator size={16} /> },
  { id: "Deal access report", icon: <ShieldCheck size={16} /> },
  { id: "Budget vs actual", icon: <Calculator size={16} /> },
  { id: "Roll-forward", icon: <Calculator size={16} /> },
  { id: "LP report", icon: <FileText size={16} /> },
  { id: "Sourcing", icon: <Map size={16} /> },
  { id: "Candidates", icon: <Briefcase size={16} /> },
  { id: "Dashboards", icon: <BarChart3 size={16} /> },
  { id: "Targets", icon: <Map size={16} /> },
  { id: "Market shares", icon: <BarChart3 size={16} /> },
  { id: "Playbook report", icon: <ShieldCheck size={16} /> },
  { id: "Comps", icon: <Calculator size={16} /> },
  { id: "Integrations", icon: <Plug size={16} /> },
  { id: "Workflows", icon: <Workflow size={16} /> },
  { id: "Firm profile", icon: <Building2 size={16} /> },
  { id: "Review", icon: <ShieldCheck size={16} /> },
  { id: "Evals", icon: <FlaskConical size={16} /> },
];

/** Deals in the sidebar so a click goes straight to the deal's workspace. Loaded once; a failed load just hides the list. */
function DealList({ onGo }: { onGo: (tab: string) => void }) {
  const [deals, setDeals] = useState<DealRow[]>([]);
  useEffect(() => { api2.deals().then(setDeals).catch(() => setDeals([])); }, []);
  if (deals.length === 0) return null;
  return (
    <div className="mt-4 border-t border-line pt-3">
      <p className="mb-1 px-2.5 text-[11px] font-medium uppercase tracking-wider text-mut">Deals</p>
      {deals.slice(0, 8).map((d) => (
        <button key={d.name} onClick={() => onGo("Deals")} className="mb-0.5 flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-sm text-mut hover:bg-sunk hover:text-fg">
          <span className="truncate">{d.name}</span><span className="ml-2 text-[11px] uppercase">{d.stage}</span>
        </button>
      ))}
    </div>
  );
}

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
        <DealList onGo={setTab} />
        <button onClick={() => { setApiKey(""); check(); }} className="mt-auto flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-mut hover:bg-sunk"><LogOut size={16} />Sign out</button>
      </nav>
      <CommandPalette items={[
        ...NAV.map((n) => ({ id: `nav-${n.id}`, label: n.id, hint: "Section", run: () => setTab(n.id) })),
      ]} />
      <SourceProvider>
        {tab === "Home" && (
          <div className="flex h-full flex-col overflow-y-auto">
            <div className="mx-auto h-72 w-full max-w-3xl px-6 pt-6"><Inbox onGo={setTab} /></div>
            <div className="min-h-0 flex-1"><Chat /></div>
          </div>
        )}
        {tab === "Documents" && <Documents />}
        {tab === "Deals" && <Deals />}
        {tab === "Portfolio" && <PortfolioPanel />}
        {tab === "Covenants" && <Covenants />}
        {tab === "Memo" && <Flagship />}
        {tab === "LBO" && <Lbo />}
        {tab === "QoE" && <Qoe />}
        {tab === "DD Q&A" && <DDQa />}
        {tab === "LBO ties" && <LboTies />}
        {tab === "Email review" && <EmailReview />}
        {tab === "Meetings" && <DealMeetings />}
        {tab === "Peer sets" && <PeerSets />}
        {tab === "People" && <People />}
        {tab === "Research deck" && <ResearchDeck />}
        {tab === "Document access" && <DocumentAccess />}
        {tab === "Valuation history" && <ValuationRounds />}
        {tab === "Deal access report" && <AccessReport />}
        {tab === "Market shares" && <MarketShares />}
        {tab === "Playbook report" && <PlaybookReport />}
        {tab === "Budget vs actual" && <BudgetVsActual />}
        {tab === "Roll-forward" && <RollForward />}
        {tab === "LP report" && <LpReport />}
        {tab === "MNPI wall" && <MnpiWall />}
        {tab === "IC review" && <IcReview />}
        {tab === "Sourcing" && <Sourcing />}
        {tab === "Candidates" && <CandidateWatch />}
        {tab === "Dashboards" && <Dashboards />}
        {tab === "Targets" && <Targets />}
        {tab === "Comps" && <Comps />}
        {tab === "Integrations" && <Integrations />}
        {tab === "Workflows" && <Workflows />}
        {tab === "Firm profile" && <Firm />}
        {tab === "Review" && <ReviewQueue />}
        {tab === "Evals" && <EvalDashboard />}
      </SourceProvider>
    </div>
  );
}
