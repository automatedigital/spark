export const SIDEBAR_EXPANDED_KEY = "spark-nav-expanded";

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
  const saved = storage?.getItem(SIDEBAR_EXPANDED_KEY);
  return saved === null || saved === undefined ? true : saved === "true";
}

export function writeSidebarExpanded(expanded: boolean, storage: StorageLike | null = browserStorage()) {
  storage?.setItem(SIDEBAR_EXPANDED_KEY, String(expanded));
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
