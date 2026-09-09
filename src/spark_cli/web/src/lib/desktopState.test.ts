import { describe, expect, it } from "vitest";
import { readDesktopWorkSurface, writeDesktopWorkSurface } from "./desktopState";

function storage() {
  const values = new Map<string, string>();
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) };
}

describe("desktop work surface", () => {
  it("round trips restorable presentation state and clamps panel width", () => {
    const store = storage();
    writeDesktopWorkSurface({ page: "chat", selectedSessionId: "s-1", sidebarExpanded: true, rightPanelOpen: true, rightPanelWidth: 9999, scrollAnchor: "m-4" }, store);
    expect(readDesktopWorkSurface(store)).toMatchObject({ page: "chat", selectedSessionId: "s-1", rightPanelWidth: 720, scrollAnchor: "m-4" });
  });

  it("rejects malformed or incompatible state", () => {
    const store = storage();
    store.setItem("spark-desktop-work-surface-v1", JSON.stringify({ version: 2, page: "chat" }));
    expect(readDesktopWorkSurface(store)).toBeNull();
  });
});
