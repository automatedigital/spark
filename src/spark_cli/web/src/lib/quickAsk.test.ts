import { describe, expect, it } from "vitest";
import { normalizeQuickAsk, quickAskDestinationLabel } from "./quickAsk";
describe("Quick Ask capture", () => {
  it("preserves destination and normalizes prompt for expansion", () => {
    expect(normalizeQuickAsk({ prompt: "  inspect this  ", destination: { kind: "project", slug: "spark" } })).toEqual({ prompt: "inspect this", destination: { kind: "project", slug: "spark" }, sessionId: null });
  });
  it("labels standalone and project destinations", () => {
    expect(quickAskDestinationLabel({ kind: "chat" })).toBe("New standalone chat");
    expect(quickAskDestinationLabel({ kind: "project", slug: "spark" })).toBe("Project: spark");
  });
});
