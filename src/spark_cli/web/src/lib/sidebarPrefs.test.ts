import { describe, expect, it, vi } from "vitest";
import {
  isEditableShortcutTarget,
  isSidebarToggleShortcut,
  readSidebarExpanded,
  SIDEBAR_EXPANDED_KEY, sidebarPreferenceKey, setSidebarPreferenceScope,
  writeSidebarExpanded,
} from "./sidebarPrefs";

function storage() {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => data.set(key, value),
  };
}

describe("sidebar preferences", () => {
  it("defaults to expanded until a value is saved", () => {
    const store = storage();

    expect(readSidebarExpanded(store)).toBe(true);

    store.data.set(sidebarPreferenceKey(SIDEBAR_EXPANDED_KEY), "false");
    expect(readSidebarExpanded(store)).toBe(false);
  });

  it("persists expanded state as a string", () => {
    const store = storage();

    writeSidebarExpanded(false, store);
    expect(store.data.get(sidebarPreferenceKey(SIDEBAR_EXPANDED_KEY))).toBe("false");

    writeSidebarExpanded(true, store);
    expect(store.data.get(sidebarPreferenceKey(SIDEBAR_EXPANDED_KEY))).toBe("true");
  });

  it("recognizes the sidebar shortcut without conflicting modifiers", () => {
    expect(isSidebarToggleShortcut({ metaKey: true, key: "\\" })).toBe(true);
    expect(isSidebarToggleShortcut({ ctrlKey: true, code: "Backslash" })).toBe(true);
    expect(isSidebarToggleShortcut({ metaKey: true, shiftKey: true, key: "\\" })).toBe(false);
    expect(isSidebarToggleShortcut({ metaKey: true, key: "k" })).toBe(false);
  });

  it("ignores shortcut targets that are editable", () => {
    expect(isEditableShortcutTarget({ tagName: "input" })).toBe(true);
    expect(isEditableShortcutTarget({ tagName: "select" })).toBe(true);
    expect(isEditableShortcutTarget({ isContentEditable: true })).toBe(true);
    expect(isEditableShortcutTarget({ closest: vi.fn().mockReturnValue({}) })).toBe(true);
    expect(isEditableShortcutTarget({ tagName: "button", closest: vi.fn().mockReturnValue(null) })).toBe(false);
  });
});

describe("sidebar profile isolation", () => {
  it("separates two backends and two profiles", () => {
    expect(sidebarPreferenceKey("width", "a", "https://one")).not.toBe(sidebarPreferenceKey("width", "a", "https://two"));
    expect(sidebarPreferenceKey("width", "a", "https://one")).not.toBe(sidebarPreferenceKey("width", "b", "https://one"));
  });
  it("never silently imports unscoped preferences into another backend/profile", () => {
    const store = storage();
    store.data.set(SIDEBAR_EXPANDED_KEY, "false");
    setSidebarPreferenceScope("profile-a");
    expect(readSidebarExpanded(store)).toBe(true);
    writeSidebarExpanded(false, store);
    setSidebarPreferenceScope("profile-b");
    expect(readSidebarExpanded(store)).toBe(true);
    setSidebarPreferenceScope("profile-a");
    expect(readSidebarExpanded(store)).toBe(false);
    setSidebarPreferenceScope("unresolved");
  });
  it("storage failures do not block navigation", () => {
    const broken = { getItem: () => { throw new Error("private mode"); }, setItem: () => { throw new Error("quota"); } };
    expect(readSidebarExpanded(broken)).toBe(true);
    expect(() => writeSidebarExpanded(false, broken)).not.toThrow();
  });
});
