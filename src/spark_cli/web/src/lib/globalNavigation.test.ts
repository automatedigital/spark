import { describe, expect, it } from "vitest";
import { pageForGlobalNavTarget } from "./globalNavigation";

describe("global task navigation", () => {
  it("routes actual task links to the existing board page", () => {
    expect(pageForGlobalNavTarget({ type: "task", id: "actual-task" })).toBe("kanban");
  });
  it("keeps project and parent thread links on Chat", () => {
    expect(pageForGlobalNavTarget({ type: "project", id: "checkout" })).toBe("chat");
    expect(pageForGlobalNavTarget({ type: "thread", id: "parent" })).toBe("chat");
  });
});
