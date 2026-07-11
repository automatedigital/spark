import { describe, expect, it } from "vitest";

import {
  LIVE_STREAM_WINDOW_CHARS,
  snapshotLiveStream,
  windowLiveStream,
} from "./liveStreamWindow";

describe("live stream window", () => {
  it("keeps render state bounded while retaining the absolute stream offset", () => {
    let state = snapshotLiveStream("");
    const chunk = "0123456789".repeat(1_000);
    for (let index = 0; index < 1_000; index += 1) {
      state = windowLiveStream(state, chunk);
      expect(state.content.length).toBeLessThanOrEqual(LIVE_STREAM_WINDOW_CHARS);
    }

    expect(state.totalChars).toBe(10_000_000);
    expect(state.omittedChars).toBe(state.totalChars - state.content.length);
    expect(state.content).toBe(chunk.repeat(7).slice(-LIVE_STREAM_WINDOW_CHARS));
  });

  it("uses backend absolute offsets when appending recovery deltas", () => {
    const initial = snapshotLiveStream("a".repeat(100_000), 100_000);
    const recovered = windowLiveStream(initial, "tail", 100_004);

    expect(recovered.totalChars).toBe(100_004);
    expect(recovered.content.endsWith("tail")).toBe(true);
    expect(recovered.omittedChars).toBe(100_004 - LIVE_STREAM_WINDOW_CHARS);
  });

  it("computes code-fence metadata from only the visible bounded window", () => {
    const hiddenFence = "```\nold\n```\n";
    const snapshot = snapshotLiveStream(`${hiddenFence}${"x".repeat(LIVE_STREAM_WINDOW_CHARS)}`);
    expect(snapshot.fenceCount).toBe(0);

    const appended = windowLiveStream(snapshot, "\n```ts\nconst value = 1;\n```\n");
    expect(appended.fenceCount).toBe(2);
  });

  it("does not retain a full snapshot in visible content", () => {
    const full = "abcdef".repeat(1_000_000);
    const state = snapshotLiveStream(full);
    expect(state.content).toBe(full.slice(-LIVE_STREAM_WINDOW_CHARS));
    expect(state.totalChars).toBe(full.length);
  });
});
