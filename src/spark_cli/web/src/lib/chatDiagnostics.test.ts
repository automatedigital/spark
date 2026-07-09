import { describe, expect, it } from "vitest";
import { recoveryActionsForTurn, safeDiagnosticsJson } from "./chatDiagnostics";

const action = (id: string, actions = recoveryActionsForTurn({
  hasSession: true,
  turnState: "idle",
  streaming: false,
  hasLastUserMessage: true,
  hasAssistantOutput: true,
})) => actions.find((a) => a.id === id);

describe("chat diagnostics and recovery helpers", () => {
  it("offers recovery actions for a stale active turn", () => {
    const actions = recoveryActionsForTurn({
      hasSession: true,
      turnState: "stalled",
      streaming: true,
      hasLastUserMessage: true,
      hasAssistantOutput: true,
    });

    expect(action("reload", actions)?.enabled).toBe(true);
    expect(action("stop", actions)?.enabled).toBe(true);
    expect(action("continue", actions)?.enabled).toBe(true);
    expect(action("retry", actions)?.enabled).toBe(false);
  });

  it("enables retry only after the turn is idle", () => {
    expect(action("retry")?.enabled).toBe(true);
    const active = recoveryActionsForTurn({
      hasSession: true,
      turnState: "streaming",
      streaming: true,
      hasLastUserMessage: true,
      hasAssistantOutput: false,
    });
    expect(action("retry", active)?.enabled).toBe(false);
  });

  it("does not send a duplicate stop while stopping", () => {
    const actions = recoveryActionsForTurn({
      hasSession: true,
      turnState: "stopping",
      streaming: true,
      hasLastUserMessage: true,
      hasAssistantOutput: true,
    });
    expect(action("stop", actions)?.enabled).toBe(false);
  });

  it("redacts secrets and local paths from copied diagnostics", () => {
    const json = safeDiagnosticsJson({
      dashboard_token: "secret-token",
      nested: { Authorization: "Bearer abc", path: "/Users/joe/Developer/github/spark/file.py" },
    });
    expect(json).toContain("[Redacted]");
    expect(json).toContain("[local-path]");
    expect(json).not.toContain("secret-token");
    expect(json).not.toContain("/Users/joe");
  });
});
