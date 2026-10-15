import { afterEach, describe, expect, it, vi } from "vitest";
import { ConnectionSupervisor } from "./useEventBus";

class FakeEventSource {
  static OPEN = 1;
  static CONNECTING = 0;
  static instances: FakeEventSource[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage = null;
  onerror = null;
  constructor() { FakeEventSource.instances.push(this); }
  close() { this.readyState = 2; }
  open() { this.readyState = 1; this.onopen?.(); }
}

const supervisors: ConnectionSupervisor[] = [];
afterEach(() => {
  supervisors.forEach((supervisor) => supervisor.stop());
  supervisors.length = 0;
  FakeEventSource.instances.length = 0;
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function fixture(sequence: number) {
  vi.useFakeTimers();
  const window = Object.assign(new EventTarget(), { setInterval: globalThis.setInterval });
  vi.stubGlobal("window", window);
  vi.stubGlobal("document", Object.assign(new EventTarget(), { visibilityState: "visible" }));
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("localStorage", { getItem: () => null });
  vi.stubGlobal("sessionStorage", { setItem: vi.fn() });
  const event = { schema_version: 1, projection_version: 1, server_epoch: "epoch", sequence: 1,
    topic: "sessions.changed", entity_id: "s1", session_id: "s1", timestamp: 1,
    payload: { action: "updated", session_id: "s1", session: { id: "s1", title: "Changed while connecting" } } };
  const fetch = vi.fn(async (url: string) => ({ ok: true, json: async () => url.includes("/snapshot")
    ? { schema_version: 1, projection_version: 1, server_epoch: "epoch", sequence, shells: [], limits: { sessions: 50, messages: 200 } }
    : { requires_snapshot: false, events: [event] } }));
  vi.stubGlobal("fetch", fetch);
  const supervisor = new ConnectionSupervisor();
  supervisors.push(supervisor);
  supervisor.start();
  return { fetch, window };
}

describe("zero-cursor SSE handoff", () => {
  it("recovers the first event committed after the snapshot but before subscribe", async () => {
    const { fetch, window } = fixture(0);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    FakeEventSource.instances[0].open();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch.mock.calls[1][0]).toContain("/deltas?after_sequence=0&");
    // A normal wake now resumes after that recovered event, proving it was
    // accepted through the real cursor/parser rather than merely requested.
    window.dispatchEvent(new Event("online"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch.mock.calls[2][0]).toContain("/deltas?after_sequence=1&");
    expect(FakeEventSource.instances).toHaveLength(1);
  });

  it("adds no polling while the zero-cursor stream stays healthy", async () => {
    const { fetch } = fixture(0);
    await vi.advanceTimersByTimeAsync(0);
    FakeEventSource.instances[0].open();
    await vi.advanceTimersByTimeAsync(20_000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("leaves nonzero server replay without an additional request", async () => {
    const { fetch } = fixture(4);
    await vi.advanceTimersByTimeAsync(0);
    FakeEventSource.instances[0].open();
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
