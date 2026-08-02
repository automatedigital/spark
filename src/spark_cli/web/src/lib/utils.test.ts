import { afterEach, describe, expect, it, vi } from "vitest";
import { timeAgo } from "./utils";

describe("timeAgo", () => {
  afterEach(() => vi.useRealTimers());

  it("renders missing transient session timestamps as now instead of epoch age", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-02T15:16:00Z"));

    expect(timeAgo(0)).toBe("just now");
    expect(timeAgo(Number.NaN)).toBe("just now");
  });

  it("still renders valid epoch-second timestamps relatively", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-02T15:16:00Z"));

    expect(timeAgo(Date.now() / 1000 - 180)).toBe("3m ago");
  });
});
