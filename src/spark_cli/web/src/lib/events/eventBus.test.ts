import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BUS_RECONNECTED_TOPIC, createEventBus } from "./eventBus";

class FakeEventSource {
  static OPEN = 1;
  readyState = FakeEventSource.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(readonly url: string) {}
}

describe("event bus", () => {
  const originalEventSource = globalThis.EventSource;
  const originalWindow = globalThis.window;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
    Object.defineProperty(globalThis, "window", {
      value: {},
      configurable: true,
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    globalThis.EventSource = originalEventSource;
    Object.defineProperty(globalThis, "window", {
      value: originalWindow,
      configurable: true,
    });
  });

  it("notifies listeners and ignores malformed messages", () => {
    const created: FakeEventSource[] = [];
    const bus = createEventBus(
      (path) => `/sse${path}`,
      (url) => {
        const source = new FakeEventSource(url);
        created.push(source);
        return source as unknown as EventSource;
      },
    );
    const events: string[] = [];

    const unsubscribe = bus.subscribe((env) => events.push(env.topic));

    expect(created[0]?.url).toBe(
      "/sse/api/events?topics=sessions%2Cchat%2Cworkspace%2Ccanvas%2Cskills%2Cmemory%2Cnotifications",
    );
    created[0]?.onmessage?.({ data: JSON.stringify({ topic: "chat.token", ts: 1, data: {} }) });
    created[0]?.onmessage?.({ data: "not-json" });

    expect(events).toEqual(["chat.token"]);
    unsubscribe();
    expect(created[0]?.close).toHaveBeenCalled();
  });

  it("emits a reconnect topic after a dropped SSE connection reopens", () => {
    const created: FakeEventSource[] = [];
    const bus = createEventBus(
      (path) => path,
      (url) => {
        const source = new FakeEventSource(url);
        created.push(source);
        return source as unknown as EventSource;
      },
    );
    const events: string[] = [];

    bus.subscribe((env) => events.push(env.topic));
    created[0]?.onerror?.();
    expect(created[0]?.close).toHaveBeenCalled();

    vi.advanceTimersByTime(1_000);
    expect(created).toHaveLength(2);

    created[1]?.onopen?.();
    expect(events).toEqual([BUS_RECONNECTED_TOPIC]);
  });
});
