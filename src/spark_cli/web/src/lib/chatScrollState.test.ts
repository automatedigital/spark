import { describe, expect, it } from "vitest";
import {
  distanceFromBottom,
  initialChatScrollState,
  reduceChatScrollState,
  shouldAutoScrollChat,
} from "./chatScrollState";

describe("chat scroll state", () => {
  it("tracks whether the viewport is following the bottom", () => {
    let state = initialChatScrollState(4);
    state = reduceChatScrollState(state, {
      type: "user-scroll",
      metrics: { scrollHeight: 2_000, scrollTop: 600, clientHeight: 600 },
      anchorId: "row-2",
    });

    expect(state.mode).toBe("detached");
    expect(state.anchorId).toBe("row-2");

    state = reduceChatScrollState(state, {
      type: "user-scroll",
      metrics: { scrollHeight: 2_000, scrollTop: 1_300, clientHeight: 600 },
    });

    expect(state.mode).toBe("following");
    expect(state.anchorId).toBeNull();
  });

  it("does not auto-scroll detached readers when new rows arrive", () => {
    const detached = reduceChatScrollState(initialChatScrollState(3), {
      type: "user-scroll",
      metrics: { scrollHeight: 2_000, scrollTop: 500, clientHeight: 600 },
      anchorId: "row-1",
    });
    const pending = reduceChatScrollState(detached, { type: "items-changed", itemCount: 4 });

    expect(pending.mode).toBe("pending-new-message");
    expect(shouldAutoScrollChat(pending, {
      countChanged: true,
      streaming: true,
      metrics: { scrollHeight: 2_100, scrollTop: 500, clientHeight: 600 },
    })).toBe(false);
  });

  it("auto-scrolls following readers and returns to following after a jump completes", () => {
    let state = reduceChatScrollState(initialChatScrollState(3), { type: "items-changed", itemCount: 4 });
    expect(state.mode).toBe("jumping-to-bottom");
    state = reduceChatScrollState(state, {
      type: "stream-tick",
      metrics: { scrollHeight: 2_000, scrollTop: 200, clientHeight: 600 },
    });
    expect(state.mode).toBe("jumping-to-bottom");
    expect(shouldAutoScrollChat(state, {
      countChanged: true,
      streaming: true,
      metrics: { scrollHeight: 1_000, scrollTop: 400, clientHeight: 500 },
    })).toBe(true);

    state = reduceChatScrollState(state, { type: "jump-complete", itemCount: 4 });
    expect(state.mode).toBe("following");
  });

  it("resets a newly opened session to bottom-following state", () => {
    const detached = reduceChatScrollState(initialChatScrollState(10), {
      type: "user-scroll",
      metrics: { scrollHeight: 4_000, scrollTop: 400, clientHeight: 700 },
      anchorId: "old-row",
    });

    const reset = reduceChatScrollState(detached, { type: "session-reset", itemCount: 42 });

    expect(reset).toEqual({
      mode: "following",
      lastItemCount: 42,
      anchorId: null,
    });
    expect(shouldAutoScrollChat(reset, {
      countChanged: false,
      streaming: false,
      metrics: { scrollHeight: 4_000, scrollTop: 0, clientHeight: 700 },
    })).toBe(false);
    expect(shouldAutoScrollChat(
      reduceChatScrollState(reset, { type: "jump-to-bottom", itemCount: 42 }),
      {
        countChanged: false,
        streaming: false,
        metrics: { scrollHeight: 4_000, scrollTop: 0, clientHeight: 700 },
      },
    )).toBe(true);
  });

  it("stays jumping-to-bottom while a settle check is still short of the bottom", () => {
    // Session open: jump requested, first scrollToIndex used estimated row
    // sizes, then remeasure grew scrollHeight — we are 500px short.
    let state = reduceChatScrollState(initialChatScrollState(20), {
      type: "jump-to-bottom",
      itemCount: 20,
    });
    state = reduceChatScrollState(state, {
      type: "jump-settle",
      itemCount: 20,
      metrics: { scrollHeight: 3_000, scrollTop: 1_900, clientHeight: 600 },
    });

    expect(state.mode).toBe("jumping-to-bottom");
    expect(shouldAutoScrollChat(state, {
      countChanged: false,
      streaming: false,
      metrics: { scrollHeight: 3_000, scrollTop: 1_900, clientHeight: 600 },
    })).toBe(true);

    // Once the clamp survives remeasure and we are truly at the bottom, the
    // jump completes and we return to following.
    state = reduceChatScrollState(state, {
      type: "jump-settle",
      itemCount: 20,
      metrics: { scrollHeight: 3_000, scrollTop: 2_400, clientHeight: 600 },
    });
    expect(state).toEqual({ mode: "following", lastItemCount: 20, anchorId: null });
  });

  it("ignores jump-settle when not jumping (no clobbering of detached readers)", () => {
    const detached = reduceChatScrollState(initialChatScrollState(5), {
      type: "user-scroll",
      metrics: { scrollHeight: 2_000, scrollTop: 100, clientHeight: 600 },
      anchorId: "row-1",
    });
    const after = reduceChatScrollState(detached, {
      type: "jump-settle",
      metrics: { scrollHeight: 2_000, scrollTop: 1_400, clientHeight: 600 },
    });
    expect(after).toBe(detached);
  });

  it("keeps the jump alive when a session opens with a cached transcript of equal count", () => {
    // Cached transcript already rendered (count 12); history load returns the
    // same 12 items so no items-changed fires. The session-open jump must
    // still drive a bottom clamp until it settles.
    let state = reduceChatScrollState(initialChatScrollState(12), {
      type: "jump-to-bottom",
      itemCount: 12,
    });
    state = reduceChatScrollState(state, { type: "items-changed", itemCount: 12 });
    expect(state.mode).toBe("jumping-to-bottom");
    expect(shouldAutoScrollChat(state, {
      countChanged: false,
      streaming: false,
      metrics: { scrollHeight: 5_000, scrollTop: 0, clientHeight: 700 },
    })).toBe(true);
  });

  it("measures distance from the bottom without returning negative values", () => {
    expect(distanceFromBottom({ scrollHeight: 100, scrollTop: 200, clientHeight: 50 })).toBe(0);
  });
});
