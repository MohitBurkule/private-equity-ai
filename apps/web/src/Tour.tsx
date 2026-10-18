import { useState } from "react";
import { Button } from "./ui";

// Shown once per browser. Storage can be blocked (private windows, cleared site data), so a failed read
// or write only means the tour may show again; the page works either way.
const DONE_KEY = "pe_tour_done";

interface Step { screen: string; title: string; text: string }

// Screens are named as the nav shows them; each step opens its screen so the text sits next to the real thing.
const STEPS: Step[] = [
  { screen: "Home", title: "Start on Home", text: "The inbox lists what needs you. The ask box answers across your documents and links each answer to the page it came from." },
  { screen: "Deals", title: "Deals hold the work", text: "Each deal keeps its documents, facts and workspace. Every figure links back to the page it came from." },
  { screen: "QoE", title: "Earnings bridge", text: "Quality of earnings builds EBITDA bridge lines. Each line cites the amount it came from." },
  { screen: "Covenants", title: "Covenant tests", text: "Tests run on cited facts. When none have run, the Portfolio card says so instead of showing all clear." },
];

export function Tour({ onGo, onClose }: { onGo: (screen: string) => void; onClose: () => void }) {
  const [i, setI] = useState(0);
  const step = STEPS[i];
  const go = (n: number) => { setI(n); onGo(STEPS[n].screen); };
  const close = () => {
    try { localStorage.setItem(DONE_KEY, "1"); } catch { /* blocked storage: the tour may show again */ }
    onClose();
  };
  return (
    <section role="dialog" aria-modal="false" aria-label="Guided tour"
      className="fixed inset-x-4 bottom-4 z-30 mx-auto max-w-md rounded-xl border border-line bg-panel p-4 shadow-lg md:left-56 md:right-auto md:mx-0">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-mut" aria-live="polite">Step {i + 1} of {STEPS.length}</p>
        <Button variant="ghost" onClick={close}>Skip tour</Button>
      </div>
      <h2 className="mt-1 text-sm font-semibold">{step.title}</h2>
      <p className="mt-1 text-sm text-mut">{step.text}</p>
      <div className="mt-4 flex items-center gap-2">
        <Button variant="ghost" disabled={i === 0} onClick={() => go(i - 1)}>Back</Button>
        {i < STEPS.length - 1
          ? <Button variant="primary" onClick={() => go(i + 1)}>Next</Button>
          : <Button variant="primary" onClick={close}>Done</Button>}
      </div>
    </section>
  );
}

export function tourDone(): boolean {
  try { return localStorage.getItem(DONE_KEY) === "1"; } catch { return false; }
}
