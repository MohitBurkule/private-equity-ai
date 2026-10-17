import { describe, expect, it } from "vitest";
import type { Connector } from "./api";
import { healthView } from "./integrationHealth";

const base: Connector = { name: "gmail", label: "Gmail", category: "email", auth: "oauth", status: "live", state: "connected", detail: "saved connection" };

describe("healthView", () => {
  it("is empty for rows without a saved connection", () => {
    expect(healthView({ ...base, state: "needs_key" })).toBeNull();
  });
  it("shows never synced", () => {
    expect(healthView({ ...base, health: "never_run" })?.label).toBe("Never synced");
  });
  it("shows the last run for a healthy connection", () => {
    const v = healthView({ ...base, health: "ok", last_run: "2026-10-17T10:00:00Z", last_status: "ok: 3 new, 1 unchanged" });
    expect(v).toMatchObject({ label: "Healthy", tone: "ok", reconnect: false });
    expect(v?.message).toContain("ok: 3 new");
  });
  it("offers reconnect on error", () => {
    const v = healthView({ ...base, health: "error", last_run: "2026-10-17T10:00:00Z", last_status: "token refresh failed, reconnect the account" });
    expect(v).toMatchObject({ label: "Error", tone: "warn", reconnect: true });
    expect(v?.message).toContain("reconnect the account");
  });
});
