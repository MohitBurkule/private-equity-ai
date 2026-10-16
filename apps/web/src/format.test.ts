import { expect, test } from "vitest";
import { fmtAmount } from "./format";
test("formats scaled money", () => {
  expect(fmtAmount("74039000000.000000", "USD")).toBe("$74.04B");
  expect(fmtAmount("-1500000", "GBP")).toBe("-£1.5M");
  expect(fmtAmount("0.57", "")).toBe("0.57");
  expect(fmtAmount("12", "pct")).toBe("12 pct");
  expect(fmtAmount("n/a", "USD")).toBe("n/a");
});
