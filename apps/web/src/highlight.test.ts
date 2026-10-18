import { expect, test } from "vitest";
import { quotePreview, splitAtQuote } from "./highlight";

test("finds quote across different whitespace", () => {
  const r = splitAtQuote("Cash  flows\nPurchases of PP&E   (1,577)  (1,373)", "purchases of pp&e (1,577)");
  expect(r?.match).toBe("Purchases of PP&E   (1,577)");
  expect(r?.before).toBe("Cash  flows\n");
});

test("returns null when quote is not on the page", () => {
  expect(splitAtQuote("abc", "xyz")).toBeNull();
});

test("regex characters in quote are literal", () => {
  expect(splitAtQuote("a (1,577) b", "(1,577)")?.match).toBe("(1,577)");
});

test("quote preview collapses whitespace and keeps short quotes whole", () => {
  expect(quotePreview("Purchases of\n  PP&E   (1,577)")).toBe("Purchases of PP&E (1,577)");
});

test("quote preview cuts long quotes at a word with an ellipsis", () => {
  const out = quotePreview("word ".repeat(100), 20);
  expect(out.endsWith("…")).toBe(true);
  expect(out.length).toBeLessThanOrEqual(21);
});
