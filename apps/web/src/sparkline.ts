/** Points for an SVG polyline across a width x height box. Values are scaled to their own min and max, so a flat
 * series sits mid-height instead of dividing by zero. Returns "" for fewer than two values. */
export function sparkPoints(values: number[], width: number, height: number): string {
  if (values.length < 2) return "";
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo;
  return values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = span === 0 ? height / 2 : height - ((v - lo) / span) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}
