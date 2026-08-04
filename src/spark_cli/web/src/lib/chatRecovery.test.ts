import { describe, expect, it } from "vitest";
import {
  consumeRecoverySignal,
  decideRecoveryPoll,
  initialRecoverySignalBudget,
  RECOVERY_SIGNAL_COOLDOWN_MS,
  RECOVERY_SIGNAL_WINDOW_MS,
} from "./chatRecovery";

describe("decideRecoveryPoll", () => {
  it("does not poll idle recovery while the document is hidden", () => {
    expect(decideRecoveryPoll({
      streaming: false,
      hidden: true,
      now: 10_000,
      lastEventAt: 0,
      lastTokenAt: 0,
      lastIdlePollAt: 0,
    }).poll).toBe(false);
  });

  it("still polls stale streaming recovery while the document is hidden", () => {
    expect(decideRecoveryPoll({
      streaming: true,
      hidden: true,
      now: 10_000,
      lastEventAt: 6_900,
      lastTokenAt: 9_500,
      lastIdlePollAt: 0,
    }).poll).toBe(true);
  });

  it("stays quiet while streaming SSE events are fresh", () => {
    expect(decideRecoveryPoll({
      streaming: true,
      hidden: false,
      now: 10_000,
      lastEventAt: 8_500,
      lastTokenAt: 8_500,
      lastIdlePollAt: 0,
    }).poll).toBe(false);
  });

  it("polls when streaming events or tokens go stale", () => {
    expect(decideRecoveryPoll({
      streaming: true,
      hidden: false,
      now: 10_000,
      lastEventAt: 6_900,
      lastTokenAt: 9_500,
      lastIdlePollAt: 0,
    }).poll).toBe(true);
    expect(decideRecoveryPoll({
      streaming: true,
      hidden: false,
      now: 20_000,
      lastEventAt: 19_000,
      lastTokenAt: 7_000,
      lastIdlePollAt: 0,
    }).poll).toBe(true);
  });

  it("uses a relaxed cadence for idle recovery", () => {
    expect(decideRecoveryPoll({
      streaming: false,
      hidden: false,
      now: 9_000,
      lastEventAt: 0,
      lastTokenAt: 0,
      lastIdlePollAt: 0,
    }).poll).toBe(false);
    const decision = decideRecoveryPoll({
      streaming: false,
      hidden: false,
      now: 10_000,
      lastEventAt: 0,
      lastTokenAt: 0,
      lastIdlePollAt: 0,
    });
    expect(decision.poll).toBe(true);
    expect(decision.nextIdlePollAt).toBe(10_000);
  });

  it("does not invent a reconnecting label from elapsed time", () => {
    const decision = decideRecoveryPoll({
      streaming: true,
      hidden: false,
      now: 40_000,
      lastEventAt: 0,
      lastTokenAt: 0,
      lastIdlePollAt: 0,
    });
    expect(decision.poll).toBe(true);
    expect(decision.statusLabel).toBeUndefined();
  });

  it("returns confirmed connection state and clears stale optimistic copy", () => {
    const decision = decideRecoveryPoll({
      streaming: true,
      hidden: false,
      now: 20_000,
      lastEventAt: 1_000,
      lastTokenAt: 1_000,
      lastIdlePollAt: 0,
      backend: { turnActive: true, connection: "reconnecting" },
      optimisticLabel: "Loading LLM response",
      optimisticAt: 1_000,
    });
    expect(decision).toMatchObject({
      poll: true,
      statusLabel: "Reconnecting to Spark",
      statusKind: "reconnecting",
      statusConfirmed: true,
    });

    const settled = decideRecoveryPoll({
      streaming: false,
      hidden: false,
      now: 20_000,
      lastEventAt: 1_000,
      lastTokenAt: 1_000,
      lastIdlePollAt: 20_000,
      backend: { turnActive: false },
      optimisticLabel: "Loading LLM response",
      optimisticAt: 1_000,
    });
    expect(settled).toMatchObject({ optimisticExpired: true, statusLabel: undefined, statusKind: "idle" });
  });
});

describe("recovery signal budget", () => {
  it("coalesces gap storms and permits recovery after cooldown", () => {
    const first = consumeRecoverySignal(initialRecoverySignalBudget(), 1_000);
    expect(first.allowed).toBe(true);
    const duplicate = consumeRecoverySignal(first.budget, 1_000 + RECOVERY_SIGNAL_COOLDOWN_MS - 1);
    expect(duplicate.allowed).toBe(false);
    const next = consumeRecoverySignal(duplicate.budget, 1_000 + RECOVERY_SIGNAL_COOLDOWN_MS);
    expect(next.allowed).toBe(true);
  });

  it("caps a burst and resets its window", () => {
    let budget = initialRecoverySignalBudget();
    for (const now of [1_000, 3_000, 5_000]) {
      const result = consumeRecoverySignal(budget, now);
      expect(result.allowed).toBe(true);
      budget = result.budget;
    }
    expect(consumeRecoverySignal(budget, 7_000).allowed).toBe(false);
    expect(consumeRecoverySignal(budget, 1_000 + RECOVERY_SIGNAL_WINDOW_MS).allowed).toBe(true);
  });
});
