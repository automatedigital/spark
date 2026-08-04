import { describe, expect, it } from "vitest";
import { reconcileOptimisticLabel, resolveChatStatus } from "./chatStatus";

describe("resolveChatStatus", () => {
  it("uses confirmed connection state before any optimistic turn copy", () => {
    expect(resolveChatStatus({
      turnActive: true,
      connection: "offline",
      optimisticLabel: "Loading LLM response",
    })).toMatchObject({
      kind: "offline",
      label: "Offline — waiting to reconnect",
      source: "connection",
      confirmed: true,
    });

    expect(resolveChatStatus({
      turnActive: true,
      connection: "reconnecting",
    })).toMatchObject({ kind: "reconnecting", confirmed: true });
  });

  it("uses terminal backend state even when the session is no longer active", () => {
    expect(resolveChatStatus({
      turnActive: false,
      backendState: "failed",
      backendLabel: "Provider timeout",
    })).toMatchObject({
      kind: "failed",
      label: "Provider timeout",
      source: "backend",
      confirmed: true,
    });
    expect(resolveChatStatus({
      turnActive: false,
      backendState: "interrupted",
    })).toMatchObject({ kind: "interrupted", label: "Response interrupted" });
  });

  it("does not let stale optimistic copy survive a confirmed idle response", () => {
    expect(resolveChatStatus({
      turnActive: false,
      optimisticLabel: "Loading LLM response",
      optimisticAt: 1_000,
      now: 20_000,
    })).toMatchObject({
      kind: "idle",
      label: null,
      staleOptimistic: true,
    });
  });

  it("keeps a session-confirmed active state useful without a turn label", () => {
    expect(resolveChatStatus({
      turnActive: null,
      sessionActive: true,
    })).toMatchObject({
      kind: "working",
      label: "Working",
      source: "session",
      confirmed: true,
    });
  });
});

describe("reconcileOptimisticLabel", () => {
  it("prefers a confirmed label and expires an unconfirmed label", () => {
    expect(reconcileOptimisticLabel({
      optimisticLabel: "Loading LLM response",
      optimisticAt: 1_000,
      confirmedLabel: "Streaming response",
      now: 20_000,
    })).toBe("Streaming response");
    expect(reconcileOptimisticLabel({
      optimisticLabel: "Loading LLM response",
      optimisticAt: 1_000,
      now: 20_000,
    })).toBeNull();
  });
});
