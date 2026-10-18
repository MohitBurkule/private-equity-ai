import { FileText, Minus, Plus, X } from "lucide-react";
import { createContext, useContext, useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, PageData } from "./api";
import { quotePreview, splitAtQuote } from "./highlight";
import { Badge, Button } from "./ui";

/** A citation's target: the quote, or an element id (`anchor`) or character offset (`offset`) in an HTML filing. */
interface Ref { docId: string; page: number; quote: string; anchor?: string; offset?: number }
/** A page as the drawer shows it: a PDF page image, or a filing's HTML page. */
type View =
  | { kind: "image"; url: string; highlighted: boolean }
  | { kind: "html"; html: string; highlighted: boolean };

const ZOOM_STEPS = [1, 1.25, 1.5, 2];
const IMAGE_WIDTH = 760;
const Ctx = createContext<(r: Ref) => void>(() => undefined);
export const useOpenSource = () => useContext(Ctx);

/** Right-hand drawer that shows the cited page with the quote highlighted. */
export function SourceProvider({ children }: { children: ReactNode }) {
  const [ref, setRef] = useState<Ref | null>(null);
  const [data, setData] = useState<PageData | null>(null);
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [view, setView] = useState<View | null>(null);
  const [zoomIdx, setZoomIdx] = useState(0);
  const frame = useRef<HTMLIFrameElement>(null);
  const zoom = ZOOM_STEPS[zoomIdx];

  useEffect(() => {
    if (!ref) return;
    setData(null); setErr(""); setView(null); setZoomIdx(0);
    api.page(ref.docId, ref.page).then(setData).catch((e) => setErr(String(e)));
    api.documents().then((d) => setName(d.find((x) => x.id === ref.docId)?.filename ?? "")).catch(() => undefined);
    // A PDF page is drawn as an image; a filing page is drawn from its HTML. Documents of neither kind keep the text view.
    let live = true;
    const show = (v: View) => { if (live) setView(v); else if (v.kind === "image") URL.revokeObjectURL(v.url); };
    api.pageImage(ref.docId, ref.page, ref.quote)
      .then((v) => show({ kind: "image", ...v }))
      .catch(() => api.pageHtml(ref.docId, ref.page, ref.quote, { anchor: ref.anchor, offset: ref.offset }).then((v) => show({ kind: "html", ...v })))
      .catch(() => undefined);
    return () => { live = false; };
  }, [ref]);
  useEffect(() => () => { if (view?.kind === "image") URL.revokeObjectURL(view.url); }, [view]);

  // Scroll the highlighted figure into view once a filing page has loaded, and apply zoom to it.
  const onFrameLoad = () => {
    const doc = frame.current?.contentDocument;
    if (!doc?.body) return;
    doc.body.style.zoom = String(zoom);
    doc.querySelector(".pe-hl")?.scrollIntoView({ block: "center" });
  };
  useEffect(() => {
    const doc = frame.current?.contentDocument;
    if (doc?.body) doc.body.style.zoom = String(zoom);
  }, [zoom]);

  const parts = data && ref?.quote ? splitAtQuote(data.text, ref.quote) : null;
  const canZoom = view !== null;
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
              {canZoom && (
                <div className="flex items-center gap-1">
                  <Button variant="ghost" aria-label="Zoom out" disabled={zoomIdx === 0}
                    onClick={() => setZoomIdx((i) => Math.max(0, i - 1))}><Minus size={14} /></Button>
                  <span className="w-10 text-center text-xs text-mut" aria-live="polite">{Math.round(zoom * 100)}%</span>
                  <Button variant="ghost" aria-label="Zoom in" disabled={zoomIdx === ZOOM_STEPS.length - 1}
                    onClick={() => setZoomIdx((i) => Math.min(ZOOM_STEPS.length - 1, i + 1))}><Plus size={14} /></Button>
                </div>
              )}
              <Button variant="ghost" aria-label="Close source" onClick={() => setRef(null)}><X size={16} /></Button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {err && <p role="alert" className="text-sm text-bad">{err}</p>}
              {data?.method === "ocr" && <div className="mb-3"><Badge tone="warn">Scanned page: check figures against the image</Badge></div>}
              {data?.text.startsWith("[UNRELIABLE") && <div className="mb-3"><Badge tone="bad">Failed its own arithmetic checks</Badge></div>}
              {view && (
                <div className="mb-3">
                  {view.kind === "image" ? (
                    // Drawn wider than the drawer so table figures stay legible; scroll sideways to read them.
                    <div className="overflow-x-auto rounded-lg border border-line bg-white">
                      <img src={view.url} alt={`${name || "Document"}, page ${ref.page}`}
                        style={{ width: IMAGE_WIDTH * zoom }} className="max-w-none" />
                    </div>
                  ) : (
                    // Sandboxed without scripts: the filer's markup is shown, and the parent scrolls it.
                    <iframe ref={frame} title={`${name || "Filing"}, page ${ref.page}`} sandbox="allow-same-origin"
                      srcDoc={view.html} onLoad={onFrameLoad} className="h-[560px] w-full rounded-lg border border-line bg-white" />
                  )}
                  {ref.quote && !view.highlighted && <p className="mt-2 text-xs text-warn">Quote not found on this page; check the text below.</p>}
                </div>
              )}
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

/**
 * A citation chip. Hovering or focusing it shows the quote inline, so a reader can check the claim without
 * opening the drawer. The drawer is desktop-only, so a tap pins the preview on narrow screens and opens the drawer.
 */
export function SourceChip({ docId, page, quote, anchor, offset, label }: Ref & { label?: string }) {
  const open = useOpenSource();
  const tipId = useId();
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  const preview = quote ? quotePreview(quote) : "";
  const showing = preview !== "" && (hover || pinned);
  return (
    <span className="relative inline-flex"
      onKeyDown={(e) => { if (e.key === "Escape") { setPinned(false); setHover(false); } }}>
      <button
        onClick={() => { setPinned(true); open({ docId, page, quote, anchor, offset }); }}
        onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}
        onFocus={() => setHover(true)} onBlur={() => { setHover(false); setPinned(false); }}
        aria-describedby={showing ? tipId : undefined}
        className="inline-flex items-center gap-1 rounded-md border border-acc/40 bg-acc-soft px-1.5 py-0.5 text-[11px] font-medium text-acc hover:border-acc">
        <FileText size={11} />{label ?? `p.${page}`}
      </button>
      {showing && (
        <span id={tipId} role="tooltip"
          className="absolute bottom-full left-0 z-20 mb-1.5 w-72 max-w-[min(18rem,calc(100vw-32px))] rounded-lg border border-line bg-panel p-2.5 text-left text-xs leading-snug text-fg shadow-lg">
          <span className="block font-medium text-mut">Page {page}</span>
          <span className="mt-1 block">&ldquo;{preview}&rdquo;</span>
        </span>
      )}
    </span>
  );
}
