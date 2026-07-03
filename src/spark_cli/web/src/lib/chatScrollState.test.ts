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

  it("measures distance from the bottom without returning negative values", () => {
    expect(distanceFromBottom({ scrollHeight: 100, scrollTop: 200, clientHeight: 50 })).toBe(0);
  });
});
