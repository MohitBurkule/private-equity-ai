import { useState } from "react";
import { Deals, PortfolioPanel, ReviewQueue } from "./Panels";
import { Workspace } from "./Workspace";

const TABS = ["Workspace", "Review", "Deals", "Portfolio"] as const;

export function App() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Workspace");
  return (
    <>
      <nav style={{ fontFamily: "system-ui", maxWidth: 1100, margin: "0 auto", padding: "8px 16px" }}>
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)} aria-pressed={tab === t} style={{ marginRight: 8, fontWeight: tab === t ? 700 : 400 }}>{t}</button>
        ))}
      </nav>
      <div style={{ fontFamily: "system-ui", maxWidth: 1100, margin: "0 auto", padding: "0 16px" }}>
        {tab === "Workspace" && <Workspace />}
        {tab === "Review" && <ReviewQueue />}
        {tab === "Deals" && <Deals />}
        {tab === "Portfolio" && <PortfolioPanel />}
      </div>
    </>
  );
}
