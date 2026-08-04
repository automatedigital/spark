import { describe, expect, it } from "vitest";
import type { WebTurnOutcome } from "./api";
import { buildThreadTimeline } from "./threadTimelineModel";
import { outcomeForTimelineTurn } from "./turnOutcomeModel";

function outcome(overrides: Partial<WebTurnOutcome>): WebTurnOutcome {
  return {
    turn_id: "turn-1",
    session_id: "session-1",
    user_message_id: null,
    assistant_message_id: null,
    status: "completed",
    started_at: null,
    ended_at: null,
    workspace_slug: null,
    changed_files: null,
    plan: null,
    ...overrides,
  };
}

describe("turn outcome matching", () => {
  it("retains an assistant-less failed turn outcome through its user message", () => {
    const turn = buildThreadTimeline([
      { id: "db:41", role: "user", content: "Run it" },
      { id: "failure", role: "note", text: "Backend failed", failure: true },
    ]).turns[0];
    const failed = outcome({ user_message_id: 41, status: "failed" });

    expect(outcomeForTimelineTurn(turn, [failed], false)).toBe(failed);
  });

  it("uses the latest fallback only for the active tail", () => {
    const turns = buildThreadTimeline([
      { id: "db:1", role: "user", content: "First" },
      { id: "db:2", role: "assistant", content: "Done" },
      { id: "db:3", role: "user", content: "Second" },
    ]).turns;
    const latest = outcome({ turn_id: "unknown" });

    expect(outcomeForTimelineTurn(turns[0], [latest], false)).toBeNull();
    expect(outcomeForTimelineTurn(turns[1], [latest], true)).toBe(latest);
  });
});
