import type { Report } from "./api";

/** Covenant tests that ran across the visible companies. Breaches are a subset of these, so the count says how much was checked. */
export function covenantTestCount(companies: Report["companies"]): number {
  return companies.reduce((n, c) => n + c.covenants.reduce((m, cov) => m + cov.tests.length, 0), 0);
}

/** Badge text for the covenant card: a breach count first, then how many tests passed, then what is missing. */
export function covenantBadge(report: Pick<Report, "breaches" | "companies">, tests: number): string {
  if (report.breaches.length) return `${report.breaches.length} breach`;
  if (tests) return `${tests} tests, 0 breaches`;
  return report.companies.length ? "no tests run" : "no companies";
}
