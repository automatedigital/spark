import { getApiBase } from "./apiHelpers";

export const SIDEBAR_EXPANDED_KEY = "spark-nav-expanded";
export const SIDEBAR_SCOPE_EVENT = "spark:sidebar-preference-scope";
let profileScope = "unresolved";
export function sidebarPreferenceScopeReady() { return profileScope !== "unresolved"; }
export function sidebarPreferenceKey(key: string, scope = profileScope, backend = getApiBase() || (typeof location === "undefined" ? "local" : location.origin)) {
  return `${key}:v1:${encodeURIComponent(backend)}:${scope}`;
}
export function setSidebarPreferenceScope(scope: string) {
  if (scope === profileScope) return;
  profileScope = scope;
  if (typeof window !== "undefined") window.dispatchEvent(new Event(SIDEBAR_SCOPE_EVENT));
}
export function readSidebarPreference(key: string): string | null {
  try { return browserStorage()?.getItem(sidebarPreferenceKey(key)) ?? null; } catch { return null; }
}
export function writeSidebarPreference(key: string, value: string) {
  try { browserStorage()?.setItem(sidebarPreferenceKey(key), value); } catch { /* Memory state still works. */ }
}

type StorageLike = Pick<Storage, "getItem" | "setItem">;

type KeyboardLike = {
  altKey?: boolean;
  code?: string;
  ctrlKey?: boolean;
  key?: string;
  metaKey?: boolean;
  shiftKey?: boolean;
};

type ShortcutTargetLike = {
  closest?: (selector: string) => unknown;
  isContentEditable?: boolean;
  tagName?: string;
};

function browserStorage(): StorageLike | null {
  return typeof localStorage === "undefined" ? null : localStorage;
}

export function readSidebarExpanded(storage: StorageLike | null = browserStorage()) {
  let saved: string | null | undefined;
  try { saved = storage?.getItem(sidebarPreferenceKey(SIDEBAR_EXPANDED_KEY)); } catch { return true; }
  return saved === null || saved === undefined ? true : saved === "true";
}

export function writeSidebarExpanded(expanded: boolean, storage: StorageLike | null = browserStorage()) {
  try { storage?.setItem(sidebarPreferenceKey(SIDEBAR_EXPANDED_KEY), String(expanded)); } catch { /* Optional device preference. */ }
}

export function isEditableShortcutTarget(target: EventTarget | ShortcutTargetLike | null) {
  if (!target || typeof target !== "object") return false;
  const candidate = target as ShortcutTargetLike;
  const tag = typeof candidate.tagName === "string" ? candidate.tagName.toUpperCase() : "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (candidate.isContentEditable) return true;
  return typeof candidate.closest === "function" && Boolean(candidate.closest("[contenteditable='true'],[contenteditable='']"));
}

export function isSidebarToggleShortcut(event: KeyboardLike) {
  const mod = Boolean(event.metaKey || event.ctrlKey);
  return mod && !event.altKey && !event.shiftKey && (event.code === "Backslash" || event.key === "\\");
}
