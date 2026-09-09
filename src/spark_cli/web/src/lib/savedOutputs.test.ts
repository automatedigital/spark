import { describe, expect, it, beforeEach } from "vitest";
import { getProjectHandoff, listSavedOutputs, saveOutput, saveProjectHandoff, removeSavedOutput } from "./savedOutputs";

describe("saved outputs and project handoff", () => {
  beforeEach(() => {
    const values = new Map<string, string>();
    Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
    }});
  });
  it("keeps saved outputs scoped to project and source session", () => {
    saveOutput({ id: "m1", title: "Answer", sourceSessionId: "s1", projectSlug: "alpha", content: "body" });
    saveOutput({ id: "m2", title: "Other", sourceSessionId: "s2", projectSlug: "beta", content: "body" });
    expect(listSavedOutputs("alpha").map((x) => x.id)).toEqual(["m1"]);
    expect(listSavedOutputs("beta").map((x) => x.id)).toEqual(["m2"]);
  });
  it("updates by stable id and removes without touching another project", () => {
    saveOutput({ id: "m1", title: "Old", sourceSessionId: "s1", projectSlug: "alpha", content: "old" });
    saveOutput({ id: "m1", title: "New", sourceSessionId: "s1", projectSlug: "alpha", content: "new" });
    expect(listSavedOutputs("alpha")).toHaveLength(1);
    removeSavedOutput("alpha", "m1");
    expect(listSavedOutputs("alpha")).toEqual([]);
  });
  it("persists handoff fields", () => {
    saveProjectHandoff("alpha", { decisions: "Use API", openQuestions: "Who owns it?", nextActions: "Ship" });
    expect(getProjectHandoff("alpha").decisions).toBe("Use API");
  });
});
