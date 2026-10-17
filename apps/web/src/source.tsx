import { FileText, X } from "lucide-react";
import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, PageData } from "./api";
import { splitAtQuote } from "./highlight";
import { Badge, Button } from "./ui";

interface Ref { docId: string; page: number; quote: string }
type PageImage = { url: string; highlighted: boolean };
const Ctx = createContext<(r: Ref) => void>(() => undefined);
export const useOpenSource = () => useContext(Ctx);

/** Right-hand drawer that shows the cited page with the quote highlighted. */
export function SourceProvider({ children }: { children: ReactNode }) {
  const [ref, setRef] = useState<Ref | null>(null);
  const [data, setData] = useState<PageData | null>(null);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [img, setImg] = useState<PageImage | null>(null);
  useEffect(() => {
    if (!ref) return;
    setData(null); setErr(""); setImg(null);
    api.page(ref.docId, ref.page).then(setData).catch((e) => setErr(String(e)));
    api.documents().then((d) => setName(d.find((x) => x.id === ref.docId)?.filename ?? "")).catch(() => undefined);
    // Some documents (iXBRL filings, Word files) have no PDF to draw; they keep the text view.
    let live = true;
    api.pageImage(ref.docId, ref.page, ref.quote)
      .then((v) => { if (live) setImg(v); else URL.revokeObjectURL(v.url); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [ref]);
  useEffect(() => () => { if (img) URL.revokeObjectURL(img.url); }, [img]);
  const parts = data && ref?.quote ? splitAtQuote(data.text, ref.quote) : null;
  return (
    <Ctx.Provider value={setRef}>
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-y-auto">{children}</div>
        {ref && (
          <aside aria-label="Source" className="hidden w-[420px] shrink-0 flex-col border-l border-line bg-panel lg:flex">
            <div className="flex items-center gap-2 border-b border-line px-4 py-3">
              <FileText size={16} className="text-acc" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{name || ref.docId.slice(0, 8)}</p>
                <p className="text-xs text-mut">Page {ref.page}</p>
              </div>
              <Button variant="ghost" aria-label="Close source" onClick={() => setRef(null)}><X size={16} /></Button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {err && <p role="alert" className="text-sm text-bad">{err}</p>}
              {img && (
                <div className="mb-3">
                  {/* Drawn wider than the drawer so table figures stay legible; scroll sideways to read them. */}
                  <div className="overflow-x-auto rounded-lg border border-line bg-white">
                    <img src={img.url} alt={`${name || "Document"}, page ${ref.page}`} className="w-[760px] max-w-none" />
                  </div>
                  {ref.quote && !img.highlighted && <p className="mt-2 text-xs text-warn">Quote not found on this page image; check the text below.</p>}
                </div>
              )}
              {data?.method === "ocr" && <div className="mb-3"><Badge tone="warn">Scanned page: check figures against the image</Badge></div>}
              {data?.text.startsWith("[UNRELIABLE") && <div className="mb-3"><Badge tone="bad">Failed its own arithmetic checks</Badge></div>}
              {ref.quote && data && !parts && <p className="mb-2 text-xs text-warn">Quote not found on this page.</p>}
              <pre className="whitespace-pre-wrap rounded-lg bg-sunk p-3 font-mono text-[12px] leading-relaxed">
                {parts ? (<>{parts.before}<mark>{parts.match}</mark>{parts.after}</>) : data?.text}
              </pre>
            </div>
          </aside>
        )}
      </div>
    </Ctx.Provider>
  );
}

export function SourceChip({ docId, page, quote, label }: { docId: string; page: number; quote: string; label?: string }) {
  const open = useOpenSource();
  return (
    <button onClick={() => open({ docId, page, quote })}
      className="inline-flex items-center gap-1 rounded-md border border-acc/40 bg-acc-soft px-1.5 py-0.5 text-[11px] font-medium text-acc hover:border-acc">
      <FileText size={11} />{label ?? `p.${page}`}
    </button>
  );
}
