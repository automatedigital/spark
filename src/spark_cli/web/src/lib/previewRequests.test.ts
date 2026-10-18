import { afterEach, describe, expect, it, vi } from "vitest";
import { observePreviewRequest } from "./previewRequests";
import { api } from "./api";

const observers: (() => void)[] = [];
afterEach(() => {
  observers.splice(0).forEach((stop) => stop());
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("preview read ownership", () => {
  it("never overlaps a slow scan and resumes polling after settlement", async () => {
    vi.useFakeTimers();
    let finish!: (value: string) => void;
    const request = vi.fn(() => new Promise<string>((resolve) => { finish = resolve; }));
    const apply = vi.fn();
    observers.push(observePreviewRequest(request, apply, 8000));
    await vi.advanceTimersByTimeAsync(24000);
    expect(request).toHaveBeenCalledTimes(1);
    finish("first");
    await vi.advanceTimersByTimeAsync(7999);
    expect(apply).toHaveBeenCalledWith("first");
    expect(request).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("aborts the browser request and fences a response that races teardown", async () => {
    vi.useFakeTimers();
    let finish!: (value: string) => void;
    let signal!: AbortSignal;
    const apply = vi.fn();
    const request = vi.fn((ownedSignal: AbortSignal) => {
      signal = ownedSignal;
      return new Promise<string>((resolve) => { finish = resolve; });
    });
    const stop = observePreviewRequest(request, apply, 8000);
    stop();
    expect(signal.aborted).toBe(true);
    finish("old project");
    await vi.advanceTimersByTimeAsync(24000);
    expect(apply).not.toHaveBeenCalled();
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("retries read errors but cancels scheduled work on hide", async () => {
    vi.useFakeTimers();
    const request = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue("recovered");
    const apply = vi.fn();
    const onError = vi.fn();
    const stop = observePreviewRequest(request, apply, 2000, onError);
    await vi.advanceTimersByTimeAsync(2000);
    expect(onError).toHaveBeenCalledOnce();
    expect(apply).toHaveBeenCalledWith("recovered");
    stop();
    await vi.advanceTimersByTimeAsync(6000);
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("does not turn one-shot status reads into polling", async () => {
    vi.useFakeTimers();
    const request = vi.fn().mockResolvedValue("running");
    observers.push(observePreviewRequest(request, vi.fn()));
    await vi.advanceTimersByTimeAsync(60000);
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("passes every preview observer's cancellation to fetch", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetch);
    const signal = new AbortController().signal;
    await api.detectDevServers("a/b", signal);
    await api.getWorkspacePreviewStatus("a/b", signal);
    await api.getWorkspacePreviewLogs("a/b", signal);
    await api.getWorkspacePreviewActionLog("a/b", 1, 20, signal);
    await api.streamBrowserTabs("a/b", signal);
    await api.streamBrowserTakeoverState("a/b", signal);
    await api.streamBrowserConsole("a/b", 3, signal);
    expect(fetch).toHaveBeenCalledTimes(7);
    for (const [url, init] of fetch.mock.calls) {
      expect(url).toContain("/projects/a%2Fb/preview/");
      expect(init.signal).toBe(signal);
    }
  });
});
