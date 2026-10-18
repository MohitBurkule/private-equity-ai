/** Split page text around a cited quote (whitespace-insensitive) so the viewer can mark the span. */
export function splitAtQuote(text: string, quote: string): { before: string; match: string; after: string } | null {
  const words = quote.trim().split(/\s+/).filter(Boolean).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) return null;
  const m = new RegExp(words.join("\\s+"), "i").exec(text);
  if (!m) return null;
  return { before: text.slice(0, m.index), match: m[0], after: text.slice(m.index + m[0].length) };
}

/** A short preview of a cited quote for a hover card: whitespace collapsed, cut at a word boundary with an ellipsis. */
export function quotePreview(quote: string, max = 220): string {
  const flat = quote.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  const cut = flat.slice(0, max);
  const at = cut.lastIndexOf(" ");
  return `${(at > max * 0.6 ? cut.slice(0, at) : cut).trimEnd()}…`;
}
