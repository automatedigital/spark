import { apiConnectionGeneration, fetchJSON } from "./apiHelpers";
import { sidebarPreferenceKey, sidebarPreferenceScopeGeneration } from "./sidebarPrefs";

export type PaletteCategory = "threads" | "messages" | "projects" | "jobs" | "skills";
export const paletteCategories: PaletteCategory[] = ["threads", "messages", "projects", "jobs", "skills"];
export interface PaletteItem {
  kind: "thread" | "message" | "project" | "scheduled-task" | "skill";
  id: string;
  label: string;
  description: string;
  destination?: string;
}
export interface PalettePage { items: PaletteItem[]; next: number | null }
export function paletteScope() {
  return `${apiConnectionGeneration()}:${sidebarPreferenceScopeGeneration()}:${sidebarPreferenceKey("palette")}`;
}
// One palette-specific recent snapshot, retained across the lazy dialog's unmount.
// SP05 can later adopt this read; this is not a generic domain-resource cache.
let recent: { scope: string; at: number; page: PalettePage } | undefined;
export function cachedPaletteRecent(): PalettePage | undefined {
  return recent?.scope === paletteScope() && Date.now() - recent.at < 60_000 ? recent.page : undefined;
}
export async function readPalette(category: PaletteCategory | "recent", query: string, signal: AbortSignal, offset = 0): Promise<PalettePage> {
  const scope = paletteScope();
  const page = await fetchJSON<PalettePage>(`/api/palette/${category}?${new URLSearchParams({ q: query, limit: "12", offset: String(offset) })}`, { signal });
  if (signal.aborted || scope !== paletteScope()) throw new DOMException("Retired palette read", "AbortError");
  if (category === "recent") recent = { scope, at: Date.now(), page };
  return page;
}
export function paletteItemKey(item: PaletteItem) { return `${item.kind}:${item.id}`; }
