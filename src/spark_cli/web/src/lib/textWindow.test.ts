import { describe, expect, it } from "vitest";
import { appendBoundedText, boundText, REASONING_WINDOW_CHARS } from "./textWindow";

describe("bounded text windows", () => {
  it("keeps only the tail and preserves the authoritative character count", () => {
    const bounded = boundText("a".repeat(20), 8);
    expect(bounded).toEqual({ text: "a".repeat(8), totalChars: 20, omittedChars: 12 });
  });

  it("keeps append work and retained reasoning bounded", () => {
    let state = boundText("");
    for (let i = 0; i < 100; i += 1) {
      state = appendBoundedText(state, "x".repeat(1_000), REASONING_WINDOW_CHARS);
    }
    expect(state.text).toHaveLength(REASONING_WINDOW_CHARS);
    expect(state.totalChars).toBe(100_000);
    expect(state.omittedChars).toBe(100_000 - REASONING_WINDOW_CHARS);
  });
});
