import { describe, expect, it } from "vitest";
import { nextChatTurnState, normalizeBackendPhase } from "./chatTurnState";

describe("chat turn state", () => {
  it("moves from submit to streaming when tokens arrive", () => {
    const starting = nextChatTurnState("idle", { type: "submit" });
    expect(starting).toBe("starting");
    expect(nextChatTurnState(starting, { type: "token" })).toBe("streaming");
  });

  it("keeps interrupt states through late token and tool events", () => {
    const stopping = nextChatTurnState("streaming", { type: "interrupt_requested" });
    expect(stopping).toBe("stopping");
    expect(nextChatTurnState(stopping, { type: "token" })).toBe("stopping");
    expect(nextChatTurnState(stopping, { type: "tool_end" })).toBe("stopping");

    const redirecting = nextChatTurnState("streaming", { type: "interrupt_requested", redirect: true });
    expect(redirecting).toBe("redirecting");
    expect(nextChatTurnState(redirecting, { type: "tool_start" })).toBe("redirecting");
  });

  it("clears only on turn_done or inactive reconnect", () => {
    expect(nextChatTurnState("stopping", { type: "turn_done" })).toBe("idle");
    expect(nextChatTurnState("redirecting", { type: "sse_reconnected", backendActive: false })).toBe("idle");
  });

  it("recovers active state from backend reconnect status", () => {
    expect(nextChatTurnState("idle", { type: "sse_reconnected", backendActive: true, phase: "stopping" })).toBe("stopping");
    expect(nextChatTurnState("idle", { type: "sse_reconnected", backendActive: true, phase: "redirecting" })).toBe("redirecting");
    expect(nextChatTurnState("idle", { type: "sse_reconnected", backendActive: true, phase: "tool" })).toBe("streaming");
  });

  it("keeps session migration active", () => {
    expect(nextChatTurnState("starting", { type: "session_migrated" })).toBe("streaming");
    expect(nextChatTurnState("redirecting", { type: "session_migrated" })).toBe("redirecting");
  });

  it("normalizes backend interrupt flags", () => {
    expect(normalizeBackendPhase(null, true)).toBe("stopping");
    expect(normalizeBackendPhase("redirecting", true)).toBe("redirecting");
  });
});
