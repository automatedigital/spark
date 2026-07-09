import { describe, expect, it } from "vitest";
import { decideRecoveryPoll } from "./chatRecovery";

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
});
