import type { Connector } from "./api";

export interface HealthView {
  label: string;
  tone: "ok" | "warn" | "mut";
  message: string;
  reconnect: boolean;
}

// Health of a saved connection as the integrations page shows it. Only connected rows have a saved run.
export function healthView(c: Connector): HealthView | null {
  if (c.state !== "connected" || !c.health) return null;
  if (c.health === "never_run") return { label: "Never synced", tone: "mut", message: "Not synced yet.", reconnect: false };
  if (c.health === "ok") return { label: "Healthy", tone: "ok", message: `Last sync ${c.last_run ?? "unknown"}: ${c.last_status ?? ""}`, reconnect: false };
  return { label: "Error", tone: "warn", message: c.last_status ?? "The last sync failed.", reconnect: true };
}
