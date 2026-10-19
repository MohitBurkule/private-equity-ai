import { describe, expect, it } from "vitest";
import { sparkPoints } from "./sparkline";

describe("sparkPoints", () => {
  it("needs two values to draw a line", () => {
    expect(sparkPoints([], 100, 20)).toBe("");
    expect(sparkPoints([5], 100, 20)).toBe("");
  });

  it("spans the box from the lowest to the highest value", () => {
    expect(sparkPoints([1, 3], 100, 20)).toBe("0.0,20.0 100.0,0.0");
  });

  it("sits mid-height when the series is flat", () => {
    expect(sparkPoints([4, 4, 4], 100, 20)).toBe("0.0,10.0 50.0,10.0 100.0,10.0");
  });
});
