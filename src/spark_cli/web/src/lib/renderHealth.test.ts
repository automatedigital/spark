import { afterEach, describe, expect, it, vi } from "vitest";
import {
  RENDER_HEALTH_KEY,
  persistSafeMode,
  pruneLongTasks,
  readSafeMode,
  rememberRenderHealth,
  safeModeKey,
  applyStreamRenderSnapshotState,
  shouldEnableSafeMode,
  shouldApplyStreamRenderSnapshot,
} from "./renderHealth";

function installLocalStorage() {
  const data = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => data.set(key, value),
    removeItem: (key: string) => data.delete(key),
  });
  return data;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("render health safe-mode storage", () => {
  it("persists safe mode per session", () => {
    const data = installLocalStorage();

    persistSafeMode("s1", true);
    persistSafeMode("s2", false);

    expect(data.get(safeModeKey("s1"))).toBe("true");
    expect(readSafeMode("s1")).toBe(true);
    expect(readSafeMode("s2")).toBe(false);

    persistSafeMode("s1", false);
    expect(readSafeMode("s1")).toBe(false);
  });

  it("records bounded render health metadata without content", () => {
    const data = installLocalStorage();

    rememberRenderHealth("thread-a", true, 7);

    const raw = data.get(RENDER_HEALTH_KEY);
    expect(raw).toBeTruthy();
    const snapshot = JSON.parse(raw!);
    expect(snapshot.session_id).toBe("thread-a");
    expect(snapshot.safe_mode).toBe(true);
    expect(snapshot.long_task_count).toBe(7);
    expect(snapshot).not.toHaveProperty("content");
  });
});

describe("long-task activation helpers", () => {
  it("prunes samples outside the rolling window", () => {
    const samples = [
      { start: 1, duration: 60 },
      { start: 50, duration: 60 },
      { start: 120, duration: 60 },
    ];

    expect(pruneLongTasks(samples, 130, 100)).toEqual([
      { start: 50, duration: 60 },
      { start: 120, duration: 60 },
    ]);
  });

  it("activates for repeated streaming long tasks or one severe long task", () => {
    const samples = [
      { start: 10, duration: 70 },
      { start: 20, duration: 80 },
      { start: 30, duration: 90 },
      { start: 40, duration: 100 },
    ];

    expect(shouldEnableSafeMode(samples, { streaming: true, triggerCount: 4, triggerDurationMs: 250 })).toBe(true);
    expect(shouldEnableSafeMode(samples.slice(0, 3), { streaming: true, triggerCount: 4, triggerDurationMs: 250 })).toBe(false);
    expect(shouldEnableSafeMode([{ start: 1, duration: 300 }], { streaming: false, triggerCount: 4, triggerDurationMs: 250 })).toBe(true);
  });
});

describe("stream render snapshot revision gate", () => {
  it("rejects duplicate and older backend revisions", () => {
    const state = { revision: 4, textChars: 120 };

    expect(shouldApplyStreamRenderSnapshot(state, { text: "x".repeat(120), revision: 4 })).toBe(false);
    expect(shouldApplyStreamRenderSnapshot(state, { text: "x".repeat(200), revision: 3 })).toBe(false);
    expect(shouldApplyStreamRenderSnapshot(state, { text: "x".repeat(121), revision: 4 })).toBe(true);
    expect(shouldApplyStreamRenderSnapshot(state, { text: "x".repeat(120), revision: 5 })).toBe(true);
  });

  it("falls back to monotonic text length when snapshots have no revision", () => {
    const state = { revision: 0, textChars: 20 };

    expect(shouldApplyStreamRenderSnapshot(state, { text: "x".repeat(19) })).toBe(false);
    expect(shouldApplyStreamRenderSnapshot(state, { text: "x".repeat(21) })).toBe(true);
  });

  it("updates revision and content length independently", () => {
    expect(applyStreamRenderSnapshotState(
      { revision: 7, textChars: 200 },
      { text: "x".repeat(150), revision: 8 },
    )).toEqual({ revision: 8, textChars: 200 });
  });
});
