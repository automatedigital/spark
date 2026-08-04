import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { buildThreadTimeline, type ThreadTimelineMessage } from "@/lib/threadTimelineModel";
import { MessagesTimeline } from "./MessagesTimeline";

describe("MessagesTimeline", () => {
  it("uses a centered thread shell and keeps final answers before work summaries", () => {
    const timeline = buildThreadTimeline([
      { id: "u1", role: "user", content: "Implement it", turnId: "t1" } as ThreadTimelineMessage,
      { id: "tool1", role: "tool", toolId: "tool1", name: "shell", args: {}, result: "ok", done: true, turnId: "t1" } as ThreadTimelineMessage,
      { id: "a1", role: "assistant", content: "The completed answer", turnId: "t1" } as ThreadTimelineMessage,
    ]);
    const html = renderToStaticMarkup(createElement(MessagesTimeline, { turns: timeline.turns }));

    expect(html).toContain('data-testid="messages-timeline"');
    expect(html).toContain('aria-label="Conversation thread"');
    expect(html).toContain("The completed answer");
    expect(html.indexOf("The completed answer")).toBeLessThan(html.indexOf("Completed work"));
    expect(html).toContain('data-turn-status="settled"');
  });

  it("renders a calm empty state without requiring session state", () => {
    const html = renderToStaticMarkup(createElement(MessagesTimeline, { turns: [], emptyLabel: "No messages yet" }));
    expect(html).toContain('data-testid="messages-timeline-empty"');
    expect(html).toContain("No messages yet");
  });
});
