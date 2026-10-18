// Deals a reader opened, most recent first. Kept per browser: it is a shortcut, not a record, so storage
// that is blocked or cleared only empties the list.
const KEY = "pe_recent_deals";
const MAX = 5;

/** The list with `name` moved to the front, capped at MAX. Pure so the ordering can be tested without storage. */
export function withRecent(list: string[], name: string): string[] {
  return [name, ...list.filter((n) => n !== name)].slice(0, MAX);
}

export function recentDeals(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((n): n is string => typeof n === "string").slice(0, MAX) : [];
  } catch {
    return [];
  }
}

/** Fired on window after the list changes, so a screen that shows it can re-read. */
export const RECENT_EVENT = "pe-recent-deals";

export function pushRecentDeal(name: string): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(withRecent(recentDeals(), name)));
  } catch {
    // Storage blocked: the list just stays empty.
  }
  window.dispatchEvent(new Event(RECENT_EVENT));
}
