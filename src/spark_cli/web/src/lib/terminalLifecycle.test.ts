import { afterEach, describe, expect, it, vi } from "vitest";
import { createTerminalLifecycle, type TerminalStream } from "./terminalLifecycle";
function fixture() {
  const pending: Array<(run: { run_id: string }) => void> = [];
  const streams: TerminalStream[] = [];
  const deps = {
    start: vi.fn(() => new Promise<{ run_id: string }>((resolve) => pending.push(resolve))),
    stop: vi.fn(async () => {}),
    stream: vi.fn(() => {
      const stream: TerminalStream = { onmessage: null, onerror: null, close: vi.fn() };
      streams.push(stream);
      return stream;
    }),
    state: vi.fn(), event: vi.fn(), error: vi.fn(),
  };
  return { owner: createTerminalLifecycle(deps), deps, pending, streams };
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
afterEach(() => vi.useRealTimers());
describe("terminal ownership", () => {
  it("stops a deferred acknowledgement after retirement exactly once", async () => {
    const f = fixture(); f.owner.restart(); f.owner.retire(); f.owner.retire();
    f.pending[0]({ run_id: "old" }); await flush();
    expect(f.deps.stop.mock.calls).toEqual([["old"]]);
    expect(f.deps.stream).not.toHaveBeenCalled();
  });
  it("reverse restart responses cannot replace or stop the newest run", async () => {
    const f = fixture(); f.owner.restart(); f.owner.restart();
    f.pending[1]({ run_id: "new" }); await flush();
    f.pending[0]({ run_id: "old" }); await flush();
    expect(f.deps.stream.mock.calls).toEqual([["new"]]);
    expect(f.deps.stop.mock.calls).toEqual([["old"]]);
    f.owner.retire(); expect(f.deps.stop.mock.calls).toEqual([["old"], ["new"]]);
  });
  it("retiring one project does not touch a replacement project", async () => {
    const old = fixture(); const next = fixture();
    old.owner.restart(); old.owner.retire(); next.owner.restart();
    next.pending[0]({ run_id: "replacement" }); old.pending[0]({ run_id: "retired" }); await flush();
    expect(next.deps.stop).not.toHaveBeenCalled();
    expect(old.deps.stop.mock.calls).toEqual([["retired"]]);
  });
  it("bounds stream retries and reconnects the same shell without creating another", async () => {
    vi.useFakeTimers();
    const f = fixture(); f.owner.restart(); f.pending[0]({ run_id: "live" }); await flush();
    for (let i = 0; i < 3; i++) {
      f.streams[i].onerror?.(new Event("error"));
      await vi.runAllTimersAsync();
    }
    expect(f.deps.stream).toHaveBeenCalledTimes(3);
    expect(f.deps.state).toHaveBeenLastCalledWith("disconnected", "live");
    f.owner.reconnect();
    expect(f.deps.stream).toHaveBeenLastCalledWith("live");
    expect(f.deps.start).toHaveBeenCalledTimes(1);
    expect(f.deps.stop).not.toHaveBeenCalled();
    f.owner.retire();
  });
  it("fences stale stream callbacks and cancels pending reconnect on switch", async () => {
    vi.useFakeTimers();
    const f = fixture(); f.owner.restart(); f.pending[0]({ run_id: "old" }); await flush();
    const stale = f.streams[0].onmessage;
    f.streams[0].onerror?.(new Event("error")); f.owner.restart();
    f.pending[1]({ run_id: "new" }); await flush();
    stale?.({ data: JSON.stringify({ type: "done", status: "stopped" }) } as MessageEvent);
    expect(f.deps.state).toHaveBeenLastCalledWith("connecting", "new");
    expect(f.deps.event).not.toHaveBeenCalled();
    f.owner.retire(); await vi.runAllTimersAsync();
    expect(f.deps.stream).toHaveBeenCalledTimes(2);
  });
  it("bounds synchronous reattachment failures and retains the existing run", async () => {
    vi.useFakeTimers();
    const f = fixture(); f.owner.restart(); f.pending[0]({ run_id: "live" }); await flush();
    f.deps.stream.mockImplementation(() => { throw new Error("offline"); });
    f.owner.reconnect(); await vi.runAllTimersAsync();
    expect(f.deps.state).toHaveBeenLastCalledWith("disconnected", "live");
    expect(f.deps.start).toHaveBeenCalledTimes(1);
    expect(f.deps.stop).not.toHaveBeenCalled();
    f.owner.retire();
  });
  it("reports start failure without retrying an uncertain creation", async () => {
    const f = fixture(); f.deps.start.mockRejectedValueOnce(new Error("lost ack"));
    f.owner.restart(); await flush();
    expect(f.deps.state).toHaveBeenLastCalledWith("failed", null);
    expect(f.deps.start).toHaveBeenCalledTimes(1);
  });
});
