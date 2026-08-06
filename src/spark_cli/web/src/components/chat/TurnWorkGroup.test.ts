import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { buildThreadTimeline, type ThreadTimelineMessage } from "@/lib/threadTimelineModel";
import { TurnWorkGroup } from "./TurnWorkGroup";

const turn = (messages: ThreadTimelineMessage[]) => buildThreadTimeline(messages).turns[0];

describe("TurnWorkGroup", () => {
  it("folds settled work behind a compact summary", () => {
    const html = renderToStaticMarkup(createElement(TurnWorkGroup, {
      turn: turn([
        { id: "u1", role: "user", content: "Done", turnId: "t1" } as ThreadTimelineMessage,
        { id: "tool1", role: "tool", toolId: "tool1", name: "shell", args: { command: "pwd" }, result: "/repo", done: true, turnId: "t1" } as ThreadTimelineMessage,
        { id: "a1", role: "assistant", content: "Finished", turnId: "t1" } as ThreadTimelineMessage,
      ]),
    }));

    expect(html).toContain('data-state="settled"');
    expect(html).toContain("Completed work");
    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain('data-work-item="tool"');
  });

  it("keeps active work expanded and surfaces unresolved input", () => {
    const html = renderToStaticMarkup(createElement(TurnWorkGroup, {
      turn: turn([
        { id: "u1", role: "user", content: "Run it", turnId: "t1" } as ThreadTimelineMessage,
        { id: "tool1", role: "tool", toolId: "tool1", name: "shell", args: {}, done: false, turnId: "t1" } as ThreadTimelineMessage,
        { id: "n1", role: "note", text: "Need a choice", requestedInput: { prompt: "Which environment?" }, turnId: "t1" } as ThreadTimelineMessage,
      ]),
    }));

    expect(html).toContain('data-state="awaiting-input"');
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain("Which environment?");
    expect(html).toContain('data-work-item="tool"');
    expect(html).toContain('data-work-item="requested-input"');
  });

  it("keeps failures expanded so failure details cannot be hidden by default", () => {
    const html = renderToStaticMarkup(createElement(TurnWorkGroup, {
      turn: turn([
        { id: "u1", role: "user", content: "Build", turnId: "t1" } as ThreadTimelineMessage,
        { id: "tool1", role: "tool", toolId: "tool1", name: "build", args: {}, result: "Error: failed", done: true, turnId: "t1" } as ThreadTimelineMessage,
      ]),
    }));

    expect(html).toContain('data-state="failed"');
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain('data-work-item="tool"');
    expect(html).toContain(">build</span>");
  });

  it("does not render child runs in the parent feed", () => {
    const html = renderToStaticMarkup(createElement(TurnWorkGroup, {
      turn: turn([
        { id: "u1", role: "user", content: "Delegate", turnId: "t1" } as ThreadTimelineMessage,
        { id: "tool1", role: "tool", toolId: "tool1", name: "terminal", args: {}, result: "ok", done: true, turnId: "t1" } as ThreadTimelineMessage,
        {
          id: "a1",
          role: "assistant",
          content: "Complete",
          subagents: [{ id: "child-1", name: "Worker", status: "interrupted" }],
          turnId: "t1",
        } as ThreadTimelineMessage,
      ]),
    }));

    expect(html).not.toContain("Worker");
    expect(html).not.toContain("turn-subagents");
    expect(html).toContain('data-state="settled"');
  });
});
