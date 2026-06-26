import { describe, expect, it } from "vitest";
import { pendingInitialMessageForSession } from "./sessionStore";

describe("pendingInitialMessageForSession", () => {
  it("returns the optimistic first message for its owning session", () => {
    expect(
      pendingInitialMessageForSession(
        { "thread-a": "Inspect the repo status." },
        "thread-a",
      ),
    ).toBe("Inspect the repo status.");
  });

  it("does not leak an optimistic first message into another selected session", () => {
    expect(
      pendingInitialMessageForSession(
        { "thread-b": "Say hello in one sentence." },
        "thread-a",
      ),
    ).toBeUndefined();
  });

  it("keeps multiple active-thread optimistic messages independently addressable", () => {
    const pending = {
      "thread-a": "Think for a bit and inspect the current repo status.",
      "thread-b": "Say hello in one sentence.",
    };

    expect(pendingInitialMessageForSession(pending, "thread-a")).toBe(
      "Think for a bit and inspect the current repo status.",
    );
    expect(pendingInitialMessageForSession(pending, "thread-b")).toBe(
      "Say hello in one sentence.",
    );
  });

  it("returns nothing when no session is selected", () => {
    expect(
      pendingInitialMessageForSession(
        { "thread-b": "Say hello in one sentence." },
        null,
      ),
    ).toBeUndefined();
  });
});
