import { describe, expect, it } from "vitest";
import type { Report } from "./api";
import { covenantBadge, covenantTestCount } from "./covenantSummary";

const test = { period: "2025", status: "pass", value: "1.2", threshold: "2.0" };
const company = (covenants: Report["companies"][number]["covenants"]): Report["companies"][number] =>
  ({ id: 1, name: "Acme", kpis: [], covenants }) as Report["companies"][number];
const report = (companies: Report["companies"], breaches: Report["breaches"] = []): Report => ({ companies, breaches });

describe("covenantTestCount", () => {
  it("sums tests across every covenant of every company", () => {
    const cos = [
      company([{ id: 1, kpi_metric: "leverage", operator: "<=", tests: [test, test] }]),
      company([{ id: 2, kpi_metric: "icr", operator: ">=", tests: [test] }, { id: 3, kpi_metric: "cash", operator: ">=", tests: [] }]),
    ];
    expect(covenantTestCount(cos)).toBe(3);
  });

  it("is zero when no covenant has run", () => {
    expect(covenantTestCount([company([])])).toBe(0);
    expect(covenantTestCount([])).toBe(0);
  });
});

describe("covenantBadge", () => {
  it("shows the breach count before anything else", () => {
    const r = report([company([])], [{ company: "Acme", kpi_metric: "leverage", period: "2025", status: "breach", value: "3", threshold: "2", covenant_id: 1 } as Report["breaches"][number]]);
    expect(covenantBadge(r, 4)).toBe("1 breach");
  });

  it("says how many tests ran when none breached", () => {
    expect(covenantBadge(report([company([{ id: 1, kpi_metric: "leverage", operator: "<=", tests: [test, test]}])]), 2)).toBe("2 tests, 0 breaches");
  });

  it("says no tests run when companies exist but no covenant has run", () => {
    expect(covenantBadge(report([company([])]), 0)).toBe("no tests run");
  });

  it("says no companies on an empty book", () => {
    expect(covenantBadge(report([]), 0)).toBe("no companies");
  });
});
