import { describe, expect, it } from "vitest";
import {
  chatMessagesFromHistory,
  chatMessagesFromSession,
  forkInfoFromResponse,
  latestAssistantContentLength,
} from "./chatSessionControllerHelpers";

describe("chat session controller helpers", () => {
  it("maps persisted user, assistant, reasoning, and tool messages", () => {
    const messages = chatMessagesFromSession([
      { id: "u1", role: "user", content: "hello", message_index: 4 },
      {
        id: "a1",
        role: "assistant",
        content: "answer",
        reasoning: "thinking",
        tool_calls: [{ id: "call-1", function: { name: "search" } }],
        message_index: 5,
      },
      { id: "t1", role: "tool", tool_call_id: "call-1", content: "result", result_preview: "preview" },
      { id: "sys", role: "user", content: "[System: internal]" },
    ]);

    expect(messages.map((message) => message.role)).toEqual(["user", "reasoning", "assistant", "tool"]);
    expect(messages[0]).toMatchObject({ content: "hello", sessionIdx: 4 });
    expect(messages[3]).toMatchObject({ name: "search", result: "preview", done: true });
  });

  it("filters non-transcript messages and preserves the latest assistant length", () => {
    const messages = chatMessagesFromHistory([
      { id: "u1", role: "user", content: "hello" },
      { id: "a1", role: "assistant", content: "a" },
      { id: "approval", role: "approval", content: "ignored" },
      { id: "a2", role: "assistant", content: "answer" },
    ]);

    expect(messages.map((message) => message.role)).toEqual(["user", "assistant", "assistant"]);
    expect(latestAssistantContentLength(messages)).toBe(6);
  });

  it("normalizes fork lineage for the view model", () => {
    expect(forkInfoFromResponse({
      parent_session_id: "parent",
      parent_title: "Earlier thread",
      fork_count: 2,
    })).toEqual({
      parentSessionId: "parent",
      parentTitle: "Earlier thread",
      forkCount: 2,
    });
  });
});
