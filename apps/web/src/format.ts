const SCALES: [number, string][] = [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]];
const SYMBOL: Record<string, string> = { USD: "$", GBP: "£", EUR: "€" };

/** "74039000000.000000" + "USD" -> "$74.04B". Non-numeric input is returned untouched, never guessed. */
export function fmtAmount(value: string, unit = ""): string {
  const n = Number(value);
  if (!value.trim() || !Number.isFinite(n)) return value;
  const sym = SYMBOL[unit];
  const abs = Math.abs(n);
  const hit = SCALES.find(([s]) => abs >= s);
  const body = hit ? `${trim(abs / hit[0])}${hit[1]}` : trim(abs);
  const sign = n < 0 ? "-" : "";
  return sym ? `${sign}${sym}${body}` : `${sign}${body}${unit ? " " + unit : ""}`;
}
const trim = (x: number) => x.toLocaleString("en-US", { maximumFractionDigits: x >= 100 ? 0 : 2 });
