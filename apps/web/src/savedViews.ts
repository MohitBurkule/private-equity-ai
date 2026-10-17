// Named library filters kept in this browser only. They are a per-viewer convenience: nothing is shared
// with other people or stored on the server. Storage can be blocked or full, so every read and write is
// guarded and a failure just means the views are not remembered this time.
export interface SavedView { name: string; query: string }

const KEY = "pe_library_views";

export function loadViews(storage: Pick<Storage, "getItem"> = localStorage): SavedView[] {
  try {
    const raw = storage.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((v): v is SavedView => typeof v?.name === "string" && typeof v?.query === "string");
  } catch {
    return [];
  }
}

export function saveViews(views: SavedView[], storage: Pick<Storage, "setItem"> = localStorage): boolean {
  try {
    storage.setItem(KEY, JSON.stringify(views));
    return true;
  } catch {
    return false;
  }
}
