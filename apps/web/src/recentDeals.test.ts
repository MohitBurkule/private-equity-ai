import { expect, test } from "vitest";
import { withRecent } from "./recentDeals";

test("opening a deal puts it first and drops its older entry", () => {
  expect(withRecent(["A", "B", "C"], "B")).toEqual(["B", "A", "C"]);
});

test("the list keeps five deals", () => {
  expect(withRecent(["A", "B", "C", "D", "E"], "F")).toEqual(["F", "A", "B", "C", "D"]);
});
