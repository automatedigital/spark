import { describe, expect, it } from "vitest";
import type { SubagentRun } from "@/lib/api";
import {
  mergeSubagentLiveEvents,
  mergeSubagentLiveEvent,
  mergeSubagentSnapshot,
  preserveSelectedSubagentId,
  subagentDisplayName,
  subagentVisual,
} from "./subagents";

describe("subagent state merger", () => {
  it("normalizes and sorts snapshot runs", () => {
    const runs = mergeSubagentSnapshot([], [
      { id: "b", status: "running", task: "second", started_at: 20 },
      { id: "a", status: "queued", goal: "first", started_at: 10 },
    ] as SubagentRun[]);

    expect(runs.map((run) => run.id)).toEqual(["a", "b"]);
    expect(runs[0].task).toBe("first");
    expect(subagentDisplayName(runs[0], 0)).not.toBe("Agent 1");
  });

  it("merges live lifecycle and transcript events", () => {
    const started = mergeSubagentLiveEvent([], "chat.subagent.started", {
      run_id: "run-1",
      task: "Inspect the API surface",
      name: "Inspector",
      started_at: 100,
    });
    const withOutput = mergeSubagentLiveEvent(started, "chat.subagent.output", {
      run_id: "run-1",
      text: "Found the endpoint shape.",
      ts: 101,
    });
    const completed = mergeSubagentLiveEvent(withOutput, "chat.subagent.completed", {
      run_id: "run-1",
      summary: "API looks ready.",
      ended_at: 120,
    });

    expect(completed).toHaveLength(1);
    expect(completed[0]).toMatchObject({
      id: "run-1",
      name: "Inspector",
      task: "Inspect the API surface",
      status: "completed",
      ended_at: 120,
      summary: "API looks ready.",
    });
    expect(completed[0].events?.map((event) => event.text)).toContain("Found the endpoint shape.");
  });

  it("enriches from reconnect snapshots without dropping existing events", () => {
    const live = mergeSubagentLiveEvent([], "chat.subagent.output", {
      run_id: "run-2",
      task: "Read files",
      text: "Opening api.ts",
      ts: 20,
    });
    const recovered = mergeSubagentSnapshot(live, [
      {
        id: "run-2",
        status: "completed",
        task: "Read files",
        started_at: 10,
        ended_at: 30,
        summary: "Done",
      },
    ] as SubagentRun[]);

    expect(recovered[0].status).toBe("completed");
    expect(recovered[0].summary).toBe("Done");
    expect(recovered[0].events?.map((event) => event.text)).toEqual(["Opening api.ts"]);
  });

  it("suppresses duplicate live and reconnect events", () => {
    const live = mergeSubagentLiveEvents([], [
      {
        topic: "chat.subagent.output",
        data: {
          run_id: "run-dup",
          event: { id: "evt-1", type: "thinking", text: "Reading files", ts: 10 },
        },
      },
      {
        topic: "chat.subagent.output",
        data: {
          run_id: "run-dup",
          event: { id: "evt-1", type: "thinking", text: "Reading files", ts: 10 },
        },
      },
    ]);
    const recovered = mergeSubagentSnapshot(live, [
      {
        id: "run-dup",
        status: "running",
        events: [{ id: "evt-1", type: "thinking", text: "Reading files", ts: 10 }],
      },
    ] as SubagentRun[]);

    expect(recovered[0].events).toHaveLength(1);
  });

  it("does not regress terminal status when late running updates arrive", () => {
    const completed = mergeSubagentLiveEvent([], "chat.subagent.completed", {
      run_id: "run-status",
      status: "completed",
      summary: "Done",
      started_at: 10,
      ended_at: 20,
    });
    const lateOutput = mergeSubagentLiveEvent(completed, "chat.subagent.output", {
      run_id: "run-status",
      text: "Late tool log",
      ts: 19,
    });

    expect(lateOutput[0].status).toBe("completed");
    expect(lateOutput[0].events?.map((event) => event.text)).toContain("Late tool log");
  });

  it("orders status by newer terminal lifecycle events", () => {
    const running = mergeSubagentLiveEvent([], "chat.subagent.started", {
      run_id: "run-order",
      started_at: 10,
    });
    const failed = mergeSubagentLiveEvent(running, "chat.subagent.failed", {
      run_id: "run-order",
      error: "Boom",
      ended_at: 30,
    });

    expect(failed[0].status).toBe("failed");
    expect(failed[0].error).toBe("Boom");
  });

  it("preserves selected subagent while reconnect snapshots merge", () => {
    const live = mergeSubagentLiveEvent([], "chat.subagent.started", {
      run_id: "run-selected",
      task: "Keep me open",
      started_at: 10,
    });
    const recovered = mergeSubagentSnapshot(live, [
      { id: "run-selected", status: "running", task: "Keep me open", started_at: 10 },
      { id: "run-other", status: "completed", task: "Other", started_at: 11 },
    ] as SubagentRun[]);

    expect(preserveSelectedSubagentId("run-selected", recovered)).toBe("run-selected");
    expect(preserveSelectedSubagentId("missing", recovered)).toBeNull();
  });

  it("normalizes persisted lifecycle event rows into readable transcript events", () => {
    const recovered = mergeSubagentSnapshot([], [
      {
        id: "run-3",
        status: "running",
        name: "Ampere",
        task: "Research sources",
        started_at: 10,
        events: [
          {
            event_type: "tool_started",
            timestamp: 12,
            data: {
              event: "tool_started",
              payload: {
                tool: "web_search",
                preview: "frontier LLM benchmark 2026",
              },
            },
          },
        ],
      },
    ] as SubagentRun[]);

    expect(recovered[0].events?.[0]).toMatchObject({
      type: "tool_started",
      text: "frontier LLM benchmark 2026",
      tool_name: "web_search",
      ts: 12,
    });
  });

  it("assigns stable visual identity from run id", () => {
    expect(subagentVisual("same-run")).toEqual(subagentVisual("same-run"));
  });
});
