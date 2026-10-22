import { describe, expect, it } from "vitest";
import { buildComposerPromptHistoryEntries as build, canNavigateComposerHistory as guard, recallComposerPrompt as recall, stepComposerPromptHistory as step } from "./composerPromptHistory";

const entries = build([
  { id: "1", role: "user", content: "first\nline" },
  { id: "tool", role: "tool", content: "secret tool context" },
  { id: "system", role: "system", content: "system context" },
  { id: "assistant", role: "assistant", content: "response" },
  { id: "1", role: "user", content: "duplicate id" },
  { id: "empty", role: "user", content: " " },
  { id: "2", role: "user", content: "first\nline" },
  { id: "3", role: "user", content: "last" },
]);

describe("loaded composer history", () => {
  it("includes only nonempty user text, deduplicates IDs and keeps separate repeated prompts", () => {
    expect(entries).toEqual([{ id: "1", prompt: "first\nline" }, { id: "2", prompt: "first\nline" }, { id: "3", prompt: "last" }]);
  });
  it("starts at latest only from empty input and never navigates forward without browsing", () => {
    expect(step("A", null, entries, "draft", "backward")).toBeNull();
    expect(step("A", null, entries, "", "forward")).toBeNull();
    expect(step("A", null, [], "", "backward")).toBeNull();
    expect(step("A", null, entries, "", "backward")?.prompt).toBe("last");
  });
  it("restores the unsent draft after edited recall and keeps the snapshot stable", () => {
    const browse = recall("A", entries, 1, "unsent\ndraft")!;
    const next = step("A", browse, [], "edited recall", "forward")!;
    expect(next.prompt).toBe("last");
    expect(step("A", next.browse, [], "edited again", "forward")).toEqual({ browse: null, prompt: "unsent\ndraft" });
    expect(step("A", recall("A", entries, 0, "draft"), entries, "first", "backward")).toBeNull();
  });
  it("retires navigation on another thread", () => {
    const browse = recall("A", entries, 0, "private draft");
    expect(step("B", browse, [], "", "forward")).toBeNull();
    expect(step("B", browse, [{ id: "B1", prompt: "B prompt" }], "", "backward")?.prompt).toBe("B prompt");
  });
});

describe("caret and key ownership", () => {
  const base = { key: "ArrowUp", text: "one\ntwo", start: 0, end: 0, menuOpen: false, modified: false, composing: false };
  it("requires collapsed start/end boundaries, including multiline text", () => {
    expect(guard(base)).toBe(true);
    expect(guard({ ...base, start: 4, end: 4 })).toBe(false);
    expect(guard({ ...base, end: 3 })).toBe(false);
    expect(guard({ ...base, key: "ArrowDown", start: 7, end: 7 })).toBe(true);
    expect(guard({ ...base, key: "ArrowDown", start: 3, end: 3 })).toBe(false);
  });
  it("leaves menus, modified arrows, composition and other keys alone", () => {
    expect(guard({ ...base, menuOpen: true })).toBe(false);
    expect(guard({ ...base, modified: true })).toBe(false);
    expect(guard({ ...base, composing: true })).toBe(false);
    expect(guard({ ...base, key: "Enter" })).toBe(false);
  });
});
