import { describe, expect, it } from "vitest";
import { isMiddleClickCloseIntent, MIDDLE_MOUSE_BUTTON } from "./panelTabs";

describe("panel tab middle-click intent", () => {
  it("closes only the active tab on middle-click", () => {
    expect(isMiddleClickCloseIntent(MIDDLE_MOUSE_BUTTON, "files", "files")).toBe(true);
    expect(isMiddleClickCloseIntent(MIDDLE_MOUSE_BUTTON, "terminal", "files")).toBe(false);
    expect(isMiddleClickCloseIntent(0, "files", "files")).toBe(false);
  });
});
