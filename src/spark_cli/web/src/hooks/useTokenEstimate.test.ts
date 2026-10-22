import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ContextEstimate, ContextItem } from "@/lib/context";

// Drive effect cleanup before the next setup, including StrictMode's replay.
// The browser fixture separately exercises the real React renderer.
const hooks = vi.hoisted(() => ({
  states: [] as unknown[],
  cursor: 0,
  effect: null as (() => (() => void)) | null,
  writes: 0,
}));
vi.mock("react", () => ({
  useRef: (initial: unknown) => {
    const index = hooks.cursor++;
    if (!(index in hooks.states)) hooks.states[index] = { current: initial };
    return hooks.states[index];
  },
  useState: (initial: unknown) => {
    const index = hooks.cursor++;
    if (!(index in hooks.states)) hooks.states[index] = initial;
    return [hooks.states[index], (value: unknown) => {
      hooks.writes++;
      hooks.states[index] = value;
    }];
  },
  useEffect: (effect: () => (() => void)) => { hooks.effect = effect; },
}));
vi.mock("@/lib/api", () => ({ getDashboardToken: () => null }));
import { useTokenEstimate } from "./useTokenEstimate";

interface Request {
  init: RequestInit;
  resolve: (value: Response) => void;
  reject: (error: Error) => void;
}
let requests: Request[];
let cleanup: (() => void) | undefined;
const items: ContextItem[] = [];
const estimate = (tokens: number): ContextEstimate => ({
  prompt_tokens: tokens, attached_tokens: 0, pinned_tokens: 0,
  history_tokens: 0, total_tokens: tokens, context_window: 100,
  utilization: tokens / 100, warning: null, buckets: [],
});
function RenderFixture(prompt = "A", session = "session-A", context = items) {
  cleanup?.();
  hooks.cursor = 0;
  useTokenEstimate(prompt, context, session);
  cleanup = hooks.effect!();
}
function state() {
  return { estimate: hooks.states[0], loading: hooks.states[1] };
}
async function succeed(index: number, tokens: number) {
  requests[index].resolve(new Response(JSON.stringify(estimate(tokens))));
  await vi.advanceTimersByTimeAsync(0);
}
async function fail(index: number) {
  requests[index].reject(new Error("late failure"));
  await vi.advanceTimersByTimeAsync(0);
}
beforeEach(() => {
  vi.useFakeTimers();
  hooks.states = [];
  hooks.writes = 0;
  requests = [];
  cleanup = undefined;
  // Deliberately ignore abort to prove fencing independently of cancellation.
  vi.stubGlobal("fetch", vi.fn((_url: string, init: RequestInit) =>
    new Promise<Response>((resolve, reject) => requests.push({ init, resolve, reject }))));
});
afterEach(() => {
  cleanup?.();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("useTokenEstimate request ownership", () => {
  it.each(["success", "failure"])("ignores old %s after the newer estimate succeeds", async (outcome) => {
    RenderFixture();
    await vi.advanceTimersByTimeAsync(500);
    expect(requests[0].init.signal).toBeInstanceOf(AbortSignal);
    expect(requests[0].init.signal?.aborted).toBe(false);
    RenderFixture("B");
    expect(requests[0].init.signal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(500);
    await succeed(1, 20);
    if (outcome === "success") await succeed(0, 99);
    else await fail(0);
    expect(state()).toEqual({ estimate: estimate(20), loading: false });
  });

  it.each(["success", "failure"])("ignores old %s while the new request is loading", async (outcome) => {
    RenderFixture();
    await vi.advanceTimersByTimeAsync(500);
    RenderFixture("B");
    await vi.advanceTimersByTimeAsync(500);
    if (outcome === "success") await succeed(0, 99);
    else await fail(0);
    expect(state()).toEqual({ estimate: null, loading: true });
    await succeed(1, 20);
    expect(state()).toEqual({ estimate: estimate(20), loading: false });
  });

  it("retires a request immediately on a session switch, before the debounce fires", async () => {
    RenderFixture();
    await vi.advanceTimersByTimeAsync(500);
    RenderFixture("A", "session-B");
    await succeed(0, 99);
    expect(requests).toHaveLength(1);
    expect(state()).toEqual({ estimate: null, loading: false });
    await vi.advanceTimersByTimeAsync(500);
    expect(JSON.parse(requests[1].init.body as string).session_id).toBe("session-B");
    await succeed(1, 30);
    expect(state()).toEqual({ estimate: estimate(30), loading: false });
  });

  it("clears the displayed estimate when context attachments change", async () => {
    RenderFixture();
    await vi.advanceTimersByTimeAsync(500);
    await succeed(0, 10);
    RenderFixture("A", "session-A", [{ id: "note", type: "note", inclusion_mode: "full",
      content: "new context", scope: "one_turn", size_bytes: 11 }]);
    expect(state()).toEqual({ estimate: null, loading: false });
    await vi.advanceTimersByTimeAsync(500);
    expect(JSON.parse(requests[1].init.body as string).context_items[0].id).toBe("note");
  });

  it("debounces rapid edits and clears current failures", async () => {
    RenderFixture();
    await vi.advanceTimersByTimeAsync(300);
    RenderFixture("B");
    await vi.advanceTimersByTimeAsync(499);
    expect(requests).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(state().loading).toBe(true);
    await fail(0);
    expect(state()).toEqual({ estimate: null, loading: false });
  });

  it.each(["success", "failure"])("does not write after unmount on late %s", async (outcome) => {
    RenderFixture();
    await vi.advanceTimersByTimeAsync(500);
    cleanup!();
    const writes = hooks.writes;
    expect(requests[0].init.signal?.aborted).toBe(true);
    if (outcome === "success") await succeed(0, 99);
    else await fail(0);
    expect(hooks.writes).toBe(writes);
  });

  it("cancels pending debounce on unmount and supports effect replay", async () => {
    RenderFixture();
    cleanup!();
    await vi.advanceTimersByTimeAsync(500);
    expect(requests).toHaveLength(0);
    cleanup = hooks.effect!();
    await vi.advanceTimersByTimeAsync(500);
    await succeed(0, 10);
    expect(state()).toEqual({ estimate: estimate(10), loading: false });
  });
});
