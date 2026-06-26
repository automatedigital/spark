import { describe, expect, it } from "vitest";
import { shouldPollBackendActiveTurn, streamingRecoveryDecision } from "./chatRecovery";

describe("chat recovery policy", () => {
  it("requests turn-status resync after a likely missed turn_done gap", () => {
    expect(streamingRecoveryDecision(2_999, 100, null)).toEqual({
      shouldResync: false,
      statusLabel: null,
    });
    expect(streamingRecoveryDecision(3_000, 100, null)).toEqual({
      shouldResync: true,
      statusLabel: "Still working…",
    });
  });

  it("keeps progressively stronger status labels for dropped SSE gaps", () => {
    expect(streamingRecoveryDecision(12_000, 100, null)).toEqual({
      shouldResync: true,
      statusLabel: "Still waiting for backend…",
    });
    expect(streamingRecoveryDecision(30_000, 100, null)).toEqual({
      shouldResync: true,
      statusLabel: "Reconnecting…",
    });
  });

  it("resyncs provider stalls even when SSE events are recent", () => {
    expect(streamingRecoveryDecision(500, 12_000, "Thinking")).toEqual({
      shouldResync: true,
      statusLabel: "Waiting for provider response…",
    });
  });

  it("polls backend-active status only when the local UI is idle", () => {
    expect(shouldPollBackendActiveTurn("session-1", false)).toBe(true);
    expect(shouldPollBackendActiveTurn("session-1", true)).toBe(false);
    expect(shouldPollBackendActiveTurn(null, false)).toBe(false);
  });
});
