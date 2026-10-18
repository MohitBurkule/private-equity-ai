import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "./ui";

export interface PaletteItem { id: string; label: string; hint?: string; run: () => void }

/** Keyboard jump to any section or deal. Ctrl/Cmd+K toggles; Esc closes. Filters by substring, arrows move, Enter runs. */
export function CommandPalette({ items }: { items: PaletteItem[] }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => { if (open) { setQ(""); setSel(0); setTimeout(() => input.current?.focus(), 0); } }, [open]);

  const shown = useMemo(
    () => items.filter((i) => i.label.toLowerCase().includes(q.trim().toLowerCase())),
    [items, q],
  );

  if (!open) return null;

  const pick = (i: PaletteItem) => { setOpen(false); i.run(); };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-[15vh]" onMouseDown={() => setOpen(false)}>
      <div role="dialog" aria-label="Command palette" className="w-full max-w-lg overflow-hidden rounded-2xl border border-line bg-panel shadow-xl" onMouseDown={(e) => e.stopPropagation()}>
        <form className="flex items-center gap-2 border-b border-line px-4 focus-within:ring-2 focus-within:ring-inset focus-within:ring-acc" onSubmit={(e) => { e.preventDefault(); if (shown[sel]) pick(shown[sel]); }}>
          <Search size={15} className="text-mut" />
          <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setSel(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, shown.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
            }}
            aria-label="Search commands" placeholder="Jump to a section..."
            className="min-w-0 flex-1 bg-transparent py-3 text-sm outline-none placeholder:text-mut" />
          <Button type="button" onClick={() => setOpen(false)} aria-label="Close">Esc</Button>
        </form>
        <ul className="max-h-80 overflow-y-auto py-1" role="listbox">
          {shown.length === 0 && <li className="px-4 py-3 text-sm text-mut">No match.</li>}
          {shown.map((i, k) => (
            <li key={i.id} role="option" aria-selected={k === sel}>
              <button type="button" onMouseEnter={() => setSel(k)} onClick={() => pick(i)}
                className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm ${k === sel ? "bg-acc-soft text-acc" : "text-fg"}`}>
                <span>{i.label}</span>
                {i.hint && <span className="text-xs text-mut">{i.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
