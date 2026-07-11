import { describe, expect, it } from "vitest";
import { copyExactAssistantContent, exactAssistantContent } from "./exactMessage";
import { boundText, COMPLETED_TEXT_WINDOW_CHARS } from "./textWindow";

describe("exact assistant content", () => {
  it("resolves the complete saved response by its rendered database id", () => {
    const exact = "prefix" + "x".repeat(200_000);
    expect(exactAssistantContent([
      { id: "41", role: "assistant", content: exact },
      { id: "42", role: "assistant", content: "other" },
    ], "db:41")).toBe(exact);
  });

  it("does not substitute another assistant when the requested row is absent", () => {
    expect(exactAssistantContent([
      { id: "42", role: "assistant", content: "other" },
    ], "db:41")).toBeNull();
  });

  it("copies the exact oversized response while its rendered text remains bounded", async () => {
    const exact = "start-marker\n" + "x".repeat(200_000) + "\nend-marker";
    const rendered = boundText(exact, COMPLETED_TEXT_WINDOW_CHARS);
    expect(rendered.text.length).toBe(COMPLETED_TEXT_WINDOW_CHARS);
    expect(rendered.text).not.toContain("start-marker");
    const writes: string[] = [];
    const copied = await copyExactAssistantContent({
      renderedId: "db:large",
      visibleFallback: rendered.text,
      loadMessages: async () => [{ id: "large", role: "assistant", content: exact }],
      writeText: async (text) => { writes.push(text); },
    });
    expect(copied).toBe(exact);
    expect(writes).toEqual([exact]);
  });
});
