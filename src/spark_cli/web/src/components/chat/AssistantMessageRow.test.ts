import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { buildThreadTimeline, type ThreadTimelineMessage } from "@/lib/threadTimelineModel";
import { AssistantMessageRow } from "./AssistantMessageRow";

describe("AssistantMessageRow", () => {
  it("treats the answer as the primary document while keeping exact actions quiet", () => {
    const message = buildThreadTimeline([
      { id: "u1", role: "user", content: "Explain it", turnId: "turn-1" } as ThreadTimelineMessage,
      {
        id: "a1",
        role: "assistant",
        content: "## Exact answer\n\nThe saved answer stays intact.",
        usage: { totalTokens: 1200, costUsd: 0.012, model: "sol" },
        turnId: "turn-1",
      } as ThreadTimelineMessage,
    ]).turns[0].finalAnswer!;

    const html = renderToStaticMarkup(createElement(AssistantMessageRow, {
      message,
      onCopyExact: () => {},
      onPromoteToBrief: () => {},
    }));

    expect(html).toContain("Exact answer");
    expect(html).toContain("The saved answer stays intact.");
    expect(html).toContain("1.2K tokens");
    expect(html).toContain("Copy complete response");
    expect(html).toContain("Promote to brief");
    expect(html).toContain('data-message-role="assistant"');
  });
});
