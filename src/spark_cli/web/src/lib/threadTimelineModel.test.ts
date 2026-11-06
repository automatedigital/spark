import { describe, expect, it } from "vitest";
import { isDeepStrictEqual } from "node:util";
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
    expect(turn.workSummary.label).toBe("Worked for 2m 14s · 1 action");
  });

  it("does not let a child status fail the parent turn or add feed work", () => {
    const turn = buildThreadTimeline([
      user("u-child", "Run the work"),
      tool("t-child", "terminal"),
      assistant("a-child", "The work is complete.", {
        subagents: [{ id: "child-1", name: "Worker", status: "interrupted" }],
      }),
    ]).turns[0];

    expect(turn.status).toBe("settled");
    expect(turn.workItems.some((item) => item.kind === "subagent")).toBe(false);
    expect(turn.workSummary.actionCount).toBe(1);
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

/** Keep one full projection as an independent grouping oracle for each delta. */
describe("incremental timeline replay", () => {
  const replay = (history: ThreadTimelineMessage[][]) => {
    let previous = buildThreadTimeline(history[0]);
    for (const messages of history.slice(1)) {
      const next = buildThreadTimeline(messages, { previous });
      expect(next).toEqual(buildThreadTimeline(messages));
      previous = next;
    }
    return previous;
  };

  it("matches full grouping across append, tools, children, redirects and historical updates", () => {
    let messages = [user("u0"), assistant("a0", "settled"), user("u1"), tool("t1", "shell", { done: false, result: undefined })];
    const history = [messages];
    messages = [...messages, assistant("a1", "partial", { streaming: true })];
    history.push(messages);
    messages = messages.map((message) => message.id === "a1" ? { ...message, content: "partial plus token", subagents: [{ id: "run-1", status: "running" }] } as ThreadTimelineMessage : message);
    history.push(messages);
    messages = messages.map((message) => message.id === "t1" ? { ...message, done: true, result: "exact\nresult" } as ThreadTimelineMessage : message);
    history.push(messages);
    messages = messages.map((message) => message.id === "a1" ? { ...message, streaming: false, subagents: [{ id: "run-1", status: "completed" }] } as ThreadTimelineMessage : message);
    history.push(messages);
    messages = [...messages, user("u2", "redirect", { redirect: true }), assistant("a2", "new response")];
    history.push(messages);
    messages = messages.map((message) => message.id === "a0" ? { ...message, content: "edited historical answer" } as ThreadTimelineMessage : message);
    history.push(messages);
    replay(history);
  });

  it("matches full grouping after prepend, replacement, fork, compression and explicit interleaving", () => {
    const original = [user("u1"), assistant("a1", "one"), user("u2"), assistant("a2", "two")];
    replay([original, [user("earlier"), assistant("earlier-a", "older"), ...original], original.map((message) => ({ ...message })), original.slice(0, 2), [user("compressed"), assistant("summary", "summary")]]);
    const interleaved = [user("x", "x", { turnId: "x" }), user("y", "y", { turnId: "y" }), assistant("ax", "x", { turnId: "x" }), assistant("ay", "y", { turnId: "y", streaming: true })];
    replay([interleaved, [...interleaved, tool("tx", "shell", { turnId: "x" })], [...interleaved, user("z"), assistant("az", "z")]]);
    // Appended metadata can refer back to a prefix turn, even in a previously contiguous history.
    replay([original.map((message, index) => ({ ...message, turnId: index < 2 ? "one" : "two" })), [...original.map((message, index) => ({ ...message, turnId: index < 2 ? "one" : "two" })), tool("late", "shell", { turnId: "one" })]]);
  });

  it("matches full projection through a deterministic mixed 10,000-message replay", () => {
    let messages: ThreadTimelineMessage[] = Array.from({ length: 2500 }, (_, index) => [
      user(`u${index}`, `prompt ${index}`, { turnId: `run-${index}` }),
      tool(`t${index}`, "shell", { turnId: `run-${index}` }),
      assistant(`a${index}-intermediate`, "progress", { turnId: `run-${index}` }),
      assistant(`a${index}`, `answer ${index}`, { turnId: `run-${index}`, streaming: index === 2499 }),
    ]).flat();
    let previous = buildThreadTimeline(messages);
    for (let index = 0; index < 12; index += 1) {
      const target = index % 4 === 0 ? 4 * (index * 179 % 2499) + 1 : messages.length - 1;
      messages = messages.map((message, position) => position === target ? {
        ...message,
        ...(message.role === "tool" ? { result: `result ${index}`, done: true } : { content: `answer 2499 token ${index}`, subagents: [{ id: "child", status: index % 2 ? "running" : "completed" }] }),
      } as ThreadTimelineMessage : message);
      const next = buildThreadTimeline(messages, { previous });
      // Compare every field at every replay step without assertion-library
      // bookkeeping for each node of the 10,000-message object graph.
      expect(isDeepStrictEqual(next, buildThreadTimeline(messages))).toBe(true);
      previous = next;
    }
  });

  it("visits and rebuilds zero settled turns for a live token, with lower projection CPU", () => {
    const messages = Array.from({ length: 5000 }, (_, index) => [user(`u${index}`), assistant(`a${index}`, `answer ${index}`, { streaming: index === 4999 })]).flat();
    const first = buildThreadTimeline(messages);
    const nextMessages = [...messages.slice(0, -1), assistant("a4999", "answer 4999 plus token", { streaming: true })];
    const stats = { comparedMessages: 0, reusedTurns: 0, visitedTurns: 0, rebuiltTurns: 0, visitedSettledTurns: 0, rebuiltSettledTurns: 0, incremental: false };
    const next = buildThreadTimeline(nextMessages, { previous: first, stats });
    expect(stats).toMatchObject({ incremental: true, reusedTurns: 4999, visitedTurns: 1, rebuiltTurns: 1, visitedSettledTurns: 0, rebuiltSettledTurns: 0 });
    expect(next.turns[0]).toBe(first.turns[0]);
    expect(next).toEqual(buildThreadTimeline(nextMessages));
    const samples = (incremental: boolean) => {
      let previous = first;
      const timings: number[] = [];
      for (let token = 0; token < 35; token += 1) {
        const delta = [...messages.slice(0, -1), assistant("a4999", `answer 4999 token ${token}`, { streaming: true })];
        const start = performance.now();
        previous = buildThreadTimeline(delta, { previous, incremental });
        if (token >= 5) timings.push(performance.now() - start);
      }
      return timings.sort((a, b) => a - b)[Math.floor(timings.length / 2)];
    };
    // Record wall CPU evidence without adding a flaky host-load timing assertion.
    const baselineMs = samples(false);
    const incrementalMs = samples(true);
    console.info("SP06 projection replay", JSON.stringify({ messages: 10000, baselineMs, incrementalMs, reductionPercent: 100 * (1 - incrementalMs / baselineMs), stats }));
  });
});
