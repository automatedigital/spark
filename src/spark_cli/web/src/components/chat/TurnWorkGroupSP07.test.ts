import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { buildThreadTimeline, type ThreadTimelineMessage } from "@/lib/threadTimelineModel";

const bubble = vi.hoisted(() => vi.fn<(props: Record<string, unknown>) => null>(() => null));
vi.mock("./ToolCallBubble", () => ({ ToolCallBubble: bubble }));
import { TurnWorkGroup } from "./TurnWorkGroup";

describe("SP07 result ownership seam", () => {
  it("passes the existing thread and tool identity without invoking the legacy full read", () => {
    const legacy = vi.fn();
    const timeline = buildThreadTimeline([
      { id: "u", role: "user", content: "Read", turnId: "turn" },
      { id: "t", role: "tool", toolId: "call-owned", name: "read_file", args: {}, result: "preview", resultTruncated: true, done: true, turnId: "turn" },
    ] as ThreadTimelineMessage[]);
    renderToStaticMarkup(createElement(TurnWorkGroup, {
      turn: { ...timeline.turns[0], isExpanded: true }, sessionId: "thread-owned", onFetchFullResult: legacy,
    }));
    expect(bubble.mock.calls[0][0]).toMatchObject({ sessionId: "thread-owned", toolCallId: "call-owned" });
    expect(legacy).not.toHaveBeenCalled();
  });
});
