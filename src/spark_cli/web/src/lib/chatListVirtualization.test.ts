import { describe, expect, it } from "vitest";

import {
  collapseChatMessagesForVirtualizer,
  estimateChatRowSize,
  type VirtualizedChatMessage,
} from "./chatListVirtualization";

const toolMessage = (
  id: string,
  name: string,
  durationSeconds = 0.5,
): Extract<VirtualizedChatMessage, { role: "tool" }> => ({
  id,
  role: "tool",
  name,
  durationSeconds,
});

describe("chat list virtualization helpers", () => {
  it("collapses high-volume repeated tool calls into one virtual row", () => {
    const tools = Array.from({ length: 500 }, (_, index) => toolMessage(`t${index}`, "web_search", 0.25));
    const messages: VirtualizedChatMessage[] = [
      { id: "u1", role: "user", content: "find context" },
      ...tools,
      { id: "a1", role: "assistant", content: "done" },
    ];

    const collapsed = collapseChatMessagesForVirtualizer(messages, false);

    expect(collapsed).toHaveLength(3);
    expect(collapsed[1]).toMatchObject({ id: "t0", repeatCount: 499 });
    expect(collapsed[1]?.msg).toMatchObject({
      role: "tool",
      name: "web_search",
      durationSeconds: 125,
    });
  });

  it("keeps different consecutive tool names as separate rows", () => {
    const collapsed = collapseChatMessagesForVirtualizer(
      [toolMessage("read", "read_file"), toolMessage("search", "web_search")],
      false,
    );

    expect(collapsed).toHaveLength(2);
    expect(collapsed.map((item) => item.id)).toEqual(["read", "search"]);
    expect(collapsed.every((item) => item.msg !== null && item.repeatCount === 0)).toBe(true);
  });

  it("adds a typing row while streaming before assistant text arrives", () => {
    const collapsed = collapseChatMessagesForVirtualizer([{ id: "u1", role: "user", content: "hello" }], true);

    expect(collapsed.at(-1)).toEqual({ msg: null, id: "typing" });
  });

  it("does not add a typing row when the active assistant row already exists", () => {
    const collapsed = collapseChatMessagesForVirtualizer(
      [{ id: "a1", role: "assistant", content: "streaming", streaming: true }],
      true,
    );

    expect(collapsed).toHaveLength(1);
    expect(collapsed[0]?.id).toBe("a1");
  });

  it("keeps row estimates bounded for streaming stress cases", () => {
    const longAssistant = {
      msg: { id: "a1", role: "assistant", content: "word ".repeat(10_000) },
      repeatCount: 0,
      id: "a1",
    } satisfies ReturnType<typeof collapseChatMessagesForVirtualizer>[number];

    expect(estimateChatRowSize({ msg: null, id: "typing" })).toBe(56);
    expect(estimateChatRowSize(longAssistant)).toBe(900);
  });
});
