import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TimelineMinimap } from "./TimelineMinimap";
import {
  MAX_RENDERED_TIMELINE_LANDMARKS,
  buildTimelineMinimapItems,
  buildTurnLandmarks,
  limitTimelineLandmarks,
} from "./timelineMinimapModel";

describe("TimelineMinimap", () => {
  it("derives lightweight markers without reading message content", () => {
    const items = buildTimelineMinimapItems([
      { id: "u1", index: 0, role: "user" },
      { id: "a1", index: 1, role: "assistant", streaming: true },
      { id: "t1", index: 2, role: "tool", resultTruncated: true },
    ]);

    expect(items).toEqual([
      { id: "u1", index: 0, kind: "user", active: false, error: false },
      { id: "a1", index: 1, kind: "assistant", active: true, error: false },
      { id: "t1", index: 2, kind: "tool", active: false, error: true },
    ]);
  });

  it("renders marker buttons for heavy threads", () => {
    const items = buildTimelineMinimapItems(
      Array.from({ length: 9 }, (_, index) => ({
        id: `row-${index}`,
        index,
        role: index % 3 === 0 ? "user" as const : "assistant" as const,
      })),
    );
    const html = renderToStaticMarkup(createElement(TimelineMinimap, {
      items,
      visibleStartIndex: 2,
      visibleEndIndex: 4,
      onJumpToIndex: () => {},
    }));

    expect(html).toContain("aria-label=\"Chat timeline\"");
    expect(html).toContain("assistant row 3");
    expect(html).toContain("user row 7");
  });

  it("stays hidden for short threads", () => {
    const items = buildTimelineMinimapItems([
      { id: "u1", index: 0, role: "user" },
      { id: "a1", index: 1, role: "assistant" },
    ]);

    expect(renderToStaticMarkup(createElement(TimelineMinimap, {
      items,
      visibleStartIndex: 0,
      visibleEndIndex: 1,
      onJumpToIndex: () => {},
    }))).toBe("");
  });

  it("derives turn landmarks while suppressing repetitive tool noise", () => {
    const landmarks = buildTurnLandmarks([
      {
        id: "turn-1",
        userMessage: {},
        finalAnswer: {},
        status: "settled",
        workItems: [{ kind: "tool" }, { kind: "tool" }],
      },
      {
        id: "turn-2",
        userMessage: {},
        status: "failed",
        workItems: [{ kind: "tool", failed: true }],
      },
      {
        id: "turn-3",
        userMessage: {},
        status: "active",
        workItems: [{ kind: "tool" }],
      },
      {
        id: "turn-4",
        userMessage: {},
        status: "awaiting-approval",
        workItems: [{ kind: "approval", resolved: false }],
      },
    ]);

    expect(landmarks.map((item) => item.kind)).toEqual([
      "user-turn", "final-answer", "user-turn", "failure", "user-turn", "active-work", "user-turn", "approval",
    ]);
    expect(landmarks.filter((item) => item.turnIndex === 0)).toHaveLength(2);
  });

  it("renders keyboard-navigable turn landmark buttons", () => {
    const landmarks = buildTurnLandmarks(Array.from({ length: 3 }, (_, index) => ({
      id: `turn-${index}`,
      userMessage: {},
      finalAnswer: {},
      status: "settled",
      workItems: [],
    })));
    const html = renderToStaticMarkup(createElement(TimelineMinimap, {
      landmarks,
      visibleStartTurnIndex: 0,
      visibleEndTurnIndex: 1,
      onJumpToTurn: () => {},
    }));

    expect(html).toContain('aria-label="Conversation turn landmarks"');
    expect(html).toContain('data-timeline-marker');
    expect(html).toContain("Turn 2 · final answer");
  });

  it("bounds long-thread marker DOM while sampling the full range", () => {
    const landmarks = buildTurnLandmarks(Array.from({ length: 1_000 }, (_, index) => ({
      id: `turn-${index}`,
      userMessage: {},
      finalAnswer: {},
      status: index === 500 ? "failed" : "settled",
      workItems: index === 500 ? [{ kind: "tool", failed: true }] : [],
    })));
    const limited = limitTimelineLandmarks(landmarks);

    expect(limited).toHaveLength(MAX_RENDERED_TIMELINE_LANDMARKS);
    expect(limited[0].turnIndex).toBe(0);
    expect(limited.at(-1)?.turnIndex).toBe(999);
    expect(limited.some((item) => item.kind === "failure" && item.turnIndex === 500)).toBe(true);
  });
});
