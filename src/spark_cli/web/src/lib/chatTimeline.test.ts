import { describe, expect, it } from "vitest";
import type { ChatMessage } from "./chatTranscriptMerge";
import {
  appendSyntheticTypingRow,
  collapseConsecutiveToolCalls,
  deriveCollapsedMessages,
  deriveTimelineItems,
  findLiveRowIndex,
  streamingAssistantVisibleChars,
} from "./chatTimeline";

const user = (id: string, content = id): ChatMessage => ({
  id,
  role: "user",
  content,
});

const assistant = (
  id: string,
  content: string,
  streaming = false,
): ChatMessage => ({
  id,
  role: "assistant",
  content,
  streaming,
});

const tool = (
  id: string,
  name: string,
  overrides: Partial<Extract<ChatMessage, { role: "tool" }>> = {},
): ChatMessage => ({
  id,
  role: "tool",
  toolId: id,
  name,
  args: {},
  ...overrides,
});

describe("chat timeline derivation", () => {
  it("keeps mixed rows in order and starts each tool run at zero repeats", () => {
    const messages = [
      user("u1"),
      assistant("a1", "answer"),
      tool("t1", "search"),
      { id: "r1", role: "reasoning", text: "thinking" } satisfies ChatMessage,
      { id: "p1", role: "approval", approval: { command: "git push" } } satisfies ChatMessage,
      { id: "n1", role: "note", text: "Created task" } satisfies ChatMessage,
    ];

    expect(collapseConsecutiveToolCalls(messages)).toEqual(
      messages.map((msg) => ({ msg, repeatCount: 0, id: msg.id })),
    );
  });

  it("collapses consecutive same-name tools, sums durations, and keeps the first row id", () => {
    const first = tool("t1", "search", { startedAt: 10, endedAt: 12, result: "first" });
    const second = tool("t2", "search", { startedAt: 20, endedAt: 23, result: "second" });
    const third = tool("t3", "search", { durationSeconds: 4, result: "third" });

    const [collapsed] = collapseConsecutiveToolCalls([first, second, third]);

    expect(collapsed).toEqual({
      id: "t1",
      repeatCount: 2,
      msg: {
        ...third,
        startedAt: 10,
        durationSeconds: 9,
      },
    });
  });

  it("does not collapse non-consecutive or differently named tools", () => {
    const messages = [
      tool("t1", "search"),
      assistant("a1", "between"),
      tool("t2", "search"),
      tool("t3", "open"),
      tool("t4", "search"),
    ];

    expect(collapseConsecutiveToolCalls(messages).map((item) => [item.id, item.repeatCount])).toEqual([
      ["t1", 0],
      ["a1", 0],
      ["t2", 0],
      ["t3", 0],
      ["t4", 0],
    ]);
  });

  it("adds typing while streaming unless the last row is an active assistant", () => {
    const beforeFirstToken = [user("u1"), tool("t1", "search")];
    expect(deriveCollapsedMessages(beforeFirstToken, true).at(-1)).toEqual({
      msg: null,
      id: "typing",
    });
    expect(deriveCollapsedMessages([assistant("a1", "", true)], true)).toEqual([
      { msg: assistant("a1", "", true), repeatCount: 0, id: "a1" },
    ]);
    expect(deriveCollapsedMessages([assistant("a1", "answer", true)], true)).toHaveLength(1);
    expect(deriveCollapsedMessages([assistant("a1", "answer")], false)).toHaveLength(1);
  });

  it("supports explicitly appending the synthetic typing row", () => {
    const items = collapseConsecutiveToolCalls([user("u1")]);
    const withTyping = appendSyntheticTypingRow(items, [user("u1")], true);

    expect(withTyping).toEqual([
      { msg: user("u1"), repeatCount: 0, id: "u1" },
      { msg: null, id: "typing" },
    ]);
    expect(appendSyntheticTypingRow(items, [user("u1")], false)).toBe(items);
  });
});

describe("chat timeline live-row helpers", () => {
  it("returns the latest streaming assistant character count", () => {
    expect(streamingAssistantVisibleChars([
      assistant("a1", "old", true),
      tool("t1", "search"),
      assistant("a2", "latest text", true),
    ])).toBe("latest text".length);
    expect(streamingAssistantVisibleChars([assistant("a1", "done")])).toBe(0);
  });

  it("finds the latest live assistant row and ignores typing, tools, and approvals", () => {
    const items = deriveCollapsedMessages([
      user("u1"),
      assistant("a1", "first", true),
      tool("t1", "search"),
      { id: "p1", role: "approval", approval: {} } satisfies ChatMessage,
    ], true);

    expect(findLiveRowIndex(items)).toBe(1);
    expect(findLiveRowIndex([{ msg: null, id: "typing" }])).toBe(-1);
  });
});

describe("chat timeline minimap mapping", () => {
  it("maps collapsed rows, approvals, failures, truncation, active work, and typing", () => {
    const items = deriveCollapsedMessages([
      user("u1"),
      assistant("a1", "streaming", true),
      tool("t1", "run", { done: false, result: "provider failed" }),
      { id: "p1", role: "approval", approval: { command: "rm" } } satisfies ChatMessage,
      tool("t2", "read", { done: true, resultTruncated: true, result: "partial" }),
    ], true);

    expect(deriveTimelineItems(items)).toEqual([
      { id: "u1", index: 0, kind: "user", active: false, error: false },
      { id: "a1", index: 1, kind: "assistant", active: true, error: false },
      { id: "t1", index: 2, kind: "tool", active: false, error: true },
      { id: "p1", index: 3, kind: "approval", active: false, error: false },
      { id: "t2", index: 4, kind: "tool", active: false, error: true },
      { id: "typing", index: 5, kind: "typing", active: true, error: false },
    ]);
  });

  it("uses the collapsed item id and index while mapping feedback and reasoning", () => {
    const items: ReturnType<typeof deriveCollapsedMessages> = [
      { msg: { id: "feedback", role: "feedback_form" }, id: "feedback", repeatCount: 0 },
      { msg: { id: "reasoning", role: "reasoning", text: "thinking" }, id: "reasoning", repeatCount: 0 },
    ];

    expect(deriveTimelineItems(items)).toEqual([
      { id: "feedback", index: 0, kind: "feedback", active: false, error: false },
      { id: "reasoning", index: 1, kind: "reasoning", active: false, error: false },
    ]);
  });
});
