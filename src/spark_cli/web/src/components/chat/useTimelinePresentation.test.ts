import { describe, expect, it } from "vitest";
import type { ChatMessage } from "@/lib/chatTranscriptMerge";
import { isTimelineTextDelta } from "./useTimelinePresentation";

const live: ChatMessage = { id: "a", role: "assistant", content: "first", streaming: true };
describe("timeline presentation boundary", () => {
  it("coalesces only live text and its display counters without altering content", () => {
    expect(isTimelineTextDelta([live], [{ ...live, content: "first\n\n**second**", renderRevision: 2 }])).toBe(true);
    expect(live.content).toBe("first");
    expect(isTimelineTextDelta([live], [live])).toBe(false);
  });
  it("flushes terminal, decision, tool, metadata and thread replacement immediately", () => {
    for (const next of [
      [{ ...live, streaming: false }],
      [{ ...live, id: "other-thread" }],
      [{ ...live, content: "next", usage: { totalTokens: 5 } }],
      [live, { id: "p", role: "approval", approval: { command: "run" } }],
      [live, { id: "t", role: "tool", toolId: "t", name: "shell", args: {} }],
      [],
    ] as ChatMessage[][]) expect(isTimelineTextDelta([live], next)).toBe(false);
  });
});
