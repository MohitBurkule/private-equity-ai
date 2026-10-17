import { describe, expect, it } from "vitest";
import { loadViews, saveViews } from "./savedViews";

function memory(initial: string | null = null) {
  let value = initial;
  return {
    getItem: () => value,
    setItem: (_k: string, v: string) => { value = v; },
  };
}

describe("saved library views", () => {
  it("round-trips named filters", () => {
    const store = memory();
    expect(saveViews([{ name: "Acme", query: "acme" }], store)).toBe(true);
    expect(loadViews(store)).toEqual([{ name: "Acme", query: "acme" }]);
  });
  it("returns nothing for empty, corrupt or wrong-shaped storage", () => {
    expect(loadViews(memory())).toEqual([]);
    expect(loadViews(memory("{not json"))).toEqual([]);
    expect(loadViews(memory('{"name":"x"}'))).toEqual([]);
    expect(loadViews(memory('[{"name":1},{"name":"ok","query":"q"}]'))).toEqual([{ name: "ok", query: "q" }]);
  });
  it("reports a failed write instead of throwing", () => {
    const full = { setItem: () => { throw new Error("quota"); } };
    expect(saveViews([{ name: "a", query: "b" }], full)).toBe(false);
  });
});
