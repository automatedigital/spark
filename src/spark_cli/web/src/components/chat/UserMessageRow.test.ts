import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { buildThreadTimeline, type ThreadTimelineMessage } from "@/lib/threadTimelineModel";
import { UserMessageRow } from "./UserMessageRow";

describe("UserMessageRow", () => {
  it("keeps exact user copy, context chips, and session actions available", () => {
    const message = buildThreadTimeline([
      {
        id: "u1",
        role: "user",
        content: "Keep  exact spacing\n\nand the second line",
        sessionIdx: 4,
        turnId: "turn-1",
        contextItems: [{
          id: "file-1",
          type: "file",
          source_path: "src/app.ts",
          inclusion_mode: "excerpt",
          scope: "one_turn",
          size_bytes: 20,
          label: "app.ts",
        }],
      } as ThreadTimelineMessage,
    ]).turns[0].userMessage!;

    const html = renderToStaticMarkup(createElement(UserMessageRow, {
      message,
      hasSession: true,
      onEdit: () => {},
      onRetry: () => {},
      onFork: () => {},
      onCopy: () => {},
    }));

    expect(html).toContain("Keep  exact spacing");
    expect(html).toContain("and the second line");
    expect(html).toContain("app.ts");
    expect(html).toContain("Edit &amp; retry");
    expect(html).toContain("Fork from here");
    expect(html).toContain('data-message-role="user"');
  });
});
