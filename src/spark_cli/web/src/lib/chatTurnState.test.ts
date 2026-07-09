import { describe, expect, it } from "vitest";
import {
  backendTurnStatusLabel,
  nextChatTurnState,
  normalizeBackendPhase,
  recoverTurnStateFromBackend,
} from "./chatTurnState";

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

  it("recovers selected-session state from backend turn status", () => {
    expect(recoverTurnStateFromBackend({ turnActive: false, phase: "streaming" })).toBe("idle");
    expect(recoverTurnStateFromBackend({ turnActive: true, phase: "starting" })).toBe("starting");
    expect(recoverTurnStateFromBackend({ turnActive: true, phase: "stopping" })).toBe("stopping");
    expect(recoverTurnStateFromBackend({ turnActive: true, phase: "redirecting" })).toBe("redirecting");
    expect(recoverTurnStateFromBackend({ turnActive: true, phase: "provider_wait" })).toBe("streaming");
  });

  it("prefers explicit backend lifecycle state when provided", () => {
    expect(recoverTurnStateFromBackend({ turnActive: true, phase: "streaming", state: "stalled" })).toBe("stalled");
    expect(recoverTurnStateFromBackend({ turnActive: true, phase: "streaming", state: "stopping" })).toBe("stopping");
    expect(recoverTurnStateFromBackend({ turnActive: true, phase: "starting", state: "running" })).toBe("starting");
    expect(recoverTurnStateFromBackend({ turnActive: true, phase: "api", state: "streaming" })).toBe("streaming");
    expect(recoverTurnStateFromBackend({ turnActive: false, phase: "streaming", state: "not_found" })).toBe("idle");
  });

  it("lets interrupt_requested recover stopping even for unknown active phases", () => {
    expect(recoverTurnStateFromBackend({
      turnActive: true,
      phase: "provider_wait",
      interruptRequested: true,
    })).toBe("stopping");
  });

  it("maps backend heartbeat state to explicit status labels", () => {
    expect(backendTurnStatusLabel({ turnActive: false, state: "not_found" })).toBeNull();
    expect(backendTurnStatusLabel({ turnActive: true, phase: "starting", state: "running" })).toBe("Preparing agent");
    expect(backendTurnStatusLabel({ turnActive: true, phase: "api", state: "running" })).toBe("Waiting for provider response");
    expect(backendTurnStatusLabel({ turnActive: true, phase: "tool", state: "running", status: "Tool running: ls" })).toBe("Tool running: ls");
    expect(backendTurnStatusLabel({ turnActive: true, phase: "streaming", state: "streaming" })).toBe("Streaming response");
    expect(backendTurnStatusLabel({ turnActive: true, phase: "api", state: "stalled", idleForSeconds: 52.9 })).toBe("Backend stalled for 52s");
  });
});
