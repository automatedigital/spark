import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { TimelineMinimap, buildTimelineMinimapItems } from "./TimelineMinimap";

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
});
