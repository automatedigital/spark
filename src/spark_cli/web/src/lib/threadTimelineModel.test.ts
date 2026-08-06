import { describe, expect, it } from "vitest";
import type { ChatMessage } from "./chatTranscriptMerge";
import {
  buildThreadTimeline,
  type ThreadTimelineMessage,
} from "./threadTimelineModel";

const user = (id: string, content = id, extra: Record<string, unknown> = {}): ThreadTimelineMessage => ({
  id,
  role: "user",
  content,
  ...extra,
} as ThreadTimelineMessage);

const assistant = (id: string, content: string, extra: Record<string, unknown> = {}): ThreadTimelineMessage => ({
  id,
  role: "assistant",
  content,
  ...extra,
} as ThreadTimelineMessage);

const tool = (id: string, name = "shell", extra: Record<string, unknown> = {}): ThreadTimelineMessage => ({
  id,
  role: "tool",
  toolId: id,
  name,
  args: { id },
  done: true,
  result: "ok",
  ...extra,
} as ThreadTimelineMessage);

describe("thread timeline model", () => {
  it("creates stable deterministic turn boundaries and puts the final answer first", () => {
    const timeline = buildThreadTimeline([
      user("u1", "Plan it", { turnId: "alpha", timestamp: "2026-01-01T00:00:00Z" }),
      { id: "r1", role: "reasoning", text: "Think", turnId: "alpha" } as ThreadTimelineMessage,
      tool("t1", "inspect", { turnId: "alpha", timestamp: "2026-01-01T00:00:01Z" }),
      assistant("a1", "The answer", { turnId: "alpha", timestamp: "2026-01-01T00:00:02Z" }),
    ]);

    expect(timeline.turns).toHaveLength(1);
    expect(timeline.turns[0]).toMatchObject({
      id: "turn:alpha",
      userMessage: { id: "u1", content: "Plan it" },
      finalAnswer: { id: "a1", content: "The answer" },
      status: "settled",
    });
    expect(timeline.turns[0].visibleItems.map((item) => item.kind)).toEqual(["assistant", "work-summary"]);
    expect(timeline.turns[0].visibleItems[0]).toBe(timeline.turns[0].finalAnswer);
  });

  it("derives missing-ID boundaries from user messages and keeps orphan work deterministic", () => {
    const timeline = buildThreadTimeline([
      tool("orphan-tool"),
      assistant("orphan-answer", "Recovered"),
      user("u1", "First", { sessionIdx: 7 }),
      assistant("a1", "One"),
      user("u2", "Second", { sessionIdx: 8 }),
      assistant("a2", "Two"),
    ]);

    expect(timeline.turns.map((turn) => turn.id)).toEqual([
      "turn:orphan:0",
      "turn:user:u1",
      "turn:user:u2",
    ]);
    expect(timeline.turns[0].finalAnswer?.content).toBe("Recovered");
    expect(timeline.turns[1].userMessage?.content).toBe("First");
  });

  it("retains multiple assistant messages while choosing the last as the final answer", () => {
    const turn = buildThreadTimeline([
      user("u1", "Work"),
      assistant("a1", "I started", { timestamp: "2026-01-01T00:00:01Z" }),
      assistant("a2", "The completed answer", { timestamp: "2026-01-01T00:00:02Z" }),
    ]).turns[0];

    expect(turn.assistantMessages.map((message) => message.id)).toEqual(["a1", "a2"]);
    expect(turn.intermediateAssistantMessages.map((message) => message.content)).toEqual(["I started"]);
    expect(turn.finalAnswer?.id).toBe("a2");
    expect(turn.workItems.some((item) => item.kind === "assistant" && item.id.endsWith(":a1"))).toBe(true);
  });

  it("folds settled work but keeps active, interrupted, failed, and unresolved work expanded", () => {
    const settled = buildThreadTimeline([
      user("u1"),
      { id: "r1", role: "reasoning", text: "details" },
      tool("t1"),
      assistant("a1", "Done"),
    ]).turns[0];
    expect(settled.isSettled).toBe(true);
    expect(settled.isExpanded).toBe(false);
    expect(settled.visibleItems.map((item) => item.kind)).toEqual(["assistant", "work-summary"]);
    expect(settled.workSummary.label).toBe("Worked · 1 action");

    const active = buildThreadTimeline([
      user("u2"),
      assistant("a2", "Still writing", { streaming: true }),
      tool("t2", "shell", { done: false, result: undefined }),
    ]).turns[0];
    expect(active.status).toBe("active");
    expect(active.isExpanded).toBe(true);
    expect(active.visibleItems.map((item) => item.kind)).toEqual(["assistant", "work-summary", "tool"]);

    const interrupted = buildThreadTimeline([
      user("u3", "Redirect", { redirect: true }),
      { id: "n3", role: "note", text: "Interrupted by redirect" },
    ]).turns[0];
    expect(interrupted.status).toBe("interrupted");
    expect(interrupted.isExpanded).toBe(true);

    const failed = buildThreadTimeline([
      user("u4"),
      tool("t4", "build", { result: "Error: compiler failed" }),
      assistant("a4", "The build failed"),
    ]).turns[0];
    expect(failed.status).toBe("failed");
    expect(failed.visibleItems.some((item) => item.kind === "tool")).toBe(true);

    const completed = buildThreadTimeline([
      user("u5", "Inspect logs"),
      tool("t5", "terminal", { result: "The report explains how to recover from this error." }),
      assistant("a5", "The logs are healthy."),
    ]).turns[0];
    expect(completed.status).toBe("settled");
    expect(completed.workItems.some((item) => item.kind === "tool" && item.failed)).toBe(false);

    const approval = buildThreadTimeline([
      user("u6"),
      { id: "p5", role: "approval", approval: { command: "rm" } },
    ]).turns[0];
    expect(approval.status).toBe("awaiting-approval");
    expect(approval.visibleItems.some((item) => item.kind === "approval")).toBe(true);

    const requested = buildThreadTimeline([
      user("u7"),
      { id: "input6", role: "note", text: "Need input", requestedInput: { prompt: "Which option?" } },
    ]).turns[0];
    expect(requested.status).toBe("awaiting-input");
    expect(requested.visibleItems.some((item) => item.kind === "requested-input")).toBe(true);

    const feedback = buildThreadTimeline([
      user("u7"),
      { id: "feedback7", role: "feedback_form" },
    ]).turns[0];
    expect(feedback.status).toBe("awaiting-input");
    expect(feedback.visibleItems.some((item) => item.kind === "feedback")).toBe(true);
  });

  it("folds subagents and changed files into deterministic outcomes with usage and duration", () => {
    const turn = buildThreadTimeline([
      user("u1", "Implement", { turnId: "turn-1", timestamp: "2026-01-01T00:00:00Z" }),
      tool("t1", "edit", {
        turnId: "turn-1",
        startedAt: "2026-01-01T00:00:01Z",
        endedAt: "2026-01-01T00:02:14Z",
        changedFiles: [{ path: "src/a.ts", additions: 4, deletions: 1 }],
        subagent: { id: "worker-1", name: "Luna", status: "completed" },
      }),
      assistant("a1", "Implemented", {
        turnId: "turn-1",
        usage: { totalTokens: 123, costUsd: 0.01 },
        timestamp: "2026-01-01T00:02:14Z",
      }),
    ]).turns[0];

    expect(turn.subagents).toEqual([{ id: "worker-1", name: "Luna", status: "completed" }]);
    expect(turn.changedFiles).toEqual([{ path: "src/a.ts", additions: 4, deletions: 1 }]);
    expect(turn.usage).toEqual({ totalTokens: 123, costUsd: 0.01 });
    expect(turn.timestamps.durationMs).toBe(134000);
    expect(turn.workSummary.label).toBe("Worked for 2m 14s · 2 actions");
  });

  it("retains resumed-session content and uses resolved approvals as settled work", () => {
    const turn = buildThreadTimeline([
      user("u1", "Resume", { sessionIdx: 100 }),
      { id: "p1", role: "approval", approval: { command: "git" }, resolved: true },
      assistant("a1", "Resumed and complete"),
    ]).turns[0];

    expect(turn.status).toBe("settled");
    expect(turn.approvals[0].resolved).toBe(true);
    expect(turn.finalAnswer?.content).toBe("Resumed and complete");
  });

  it("shares unchanged settled turns and only replaces the changed active item", () => {
    const first = buildThreadTimeline([
      user("u1", "Finished", { turnId: "done" }),
      tool("t1", "inspect", { turnId: "done" }),
      assistant("a1", "Done", { turnId: "done" }),
      user("u2", "Active", { turnId: "active" }),
      { id: "r2", role: "reasoning", text: "same", turnId: "active" },
      assistant("a2", "Draft", { turnId: "active", streaming: true }),
    ]);
    const updated = buildThreadTimeline([
      user("u1", "Finished", { turnId: "done" }),
      tool("t1", "inspect", { turnId: "done" }),
      assistant("a1", "Done", { turnId: "done" }),
      user("u2", "Active", { turnId: "active" }),
      { id: "r2", role: "reasoning", text: "same", turnId: "active" },
      assistant("a2", "Draft plus one token", { turnId: "active", streaming: true }),
    ], { previous: first });

    expect(updated.turns[0]).toBe(first.turns[0]);
    expect(updated.turns[1].finalAnswer?.content).toBe("Draft plus one token");
    expect(updated.turns[1]).not.toBe(first.turns[1]);
    expect(updated.turns[1].workItems[0]).toBe(first.turns[1].workItems[0]);
    expect(updated.turns[1].finalAnswer).not.toBe(first.turns[1].finalAnswer);
  });

  it("returns the previous timeline when a delta has no semantic change", () => {
    const messages: ChatMessage[] = [
      { id: "u1", role: "user", content: "Hi" },
      { id: "a1", role: "assistant", content: "Hello" },
    ];
    const first = buildThreadTimeline(messages);
    const second = buildThreadTimeline(messages.map((message) => ({ ...message })), { previous: first });
    expect(second).toBe(first);
  });
});
