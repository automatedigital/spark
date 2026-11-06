import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReferenceResources, referenceResources, referenceScope, REFERENCE_TTL_MS } from "./referenceResources";
import { observeReferenceRefresh } from "@/hooks/useReferenceRefresh";
import { setSidebarPreferenceScope } from "./sidebarPrefs";

beforeEach(() => { vi.stubGlobal("localStorage", { getItem: () => null }); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
const deferred = <T>() => { let resolve!: (value: T) => void; const promise = new Promise<T>((done) => { resolve = done; }); return { promise, resolve }; };
it("deduplicates two consumers and one abort cannot cancel the other", async () => {
  const cache = new ReferenceResources(() => "A");
  const pending = deferred<string>();
  const loader = vi.fn(() => pending.promise);
  const consumer = new AbortController();
  const a = cache.read("memory", loader, consumer.signal);
  const b = cache.read("memory", loader);
  consumer.abort();
  await expect(a).rejects.toMatchObject({ name: "AbortError" });
  pending.resolve("both cards");
  expect(await b).toBe("both cards");
  expect(loader).toHaveBeenCalledTimes(1);
  expect(await cache.read("memory", loader)).toBe("both cards");
});
it("exposes freshness and errors, retries failures, and bounds lost-event staleness by TTL", async () => {
  let now = 100;
  const cache = new ReferenceResources(() => "A", () => now);
  const loader = vi.fn().mockResolvedValueOnce("before").mockRejectedValueOnce(new Error("offline")).mockResolvedValue("after");
  await cache.read("cron", loader);
  expect(cache.state("cron")).toMatchObject({ stale: false, updatedAt: 100, data: "before" });
  now += REFERENCE_TTL_MS;
  expect(cache.state("cron").stale).toBe(true);
  await expect(cache.read("cron", loader)).rejects.toThrow("offline");
  expect(cache.state("cron")).toMatchObject({ stale: true, data: "before", error: expect.any(Error) });
  expect(await cache.read("cron", loader)).toBe("after");
  expect(cache.state("cron").error).toBeUndefined();
});
it("fences an in-flight GET invalidated by a successful mutation", async () => {
  const cache = new ReferenceResources(() => "A");
  const old = deferred<string>();
  const loader = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValue("committed");
  const read = cache.read("sidebar", loader);
  await Promise.resolve();
  cache.invalidate("sidebar");
  old.resolve("obsolete");
  expect(await read).toBe("committed");
  expect(loader).toHaveBeenCalledTimes(2);
});
it("retires old profile/backend/auth reads, including A to B to A", async () => {
  let scope = "A1";
  const cache = new ReferenceResources(() => scope);
  const old = deferred<string>();
  const a = cache.read("memory", () => old.promise);
  await Promise.resolve();
  scope = "B";
  expect(await cache.read("memory", async () => "B")).toBe("B");
  scope = "A2";
  expect(await cache.read("memory", async () => "new A")).toBe("new A");
  old.resolve("old A");
  await expect(a).rejects.toMatchObject({ name: "AbortError" });
  expect(cache.state("memory").data).toBe("new A");
});
it("scope changes on profile, backend and direct credential replacement without exposing credentials", () => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null });
  const a = referenceScope();
  setSidebarPreferenceScope("SP05-profile-2");
  const b = referenceScope();
  values.set("spark_dashboard_token", "private-value");
  const c = referenceScope();
  expect(a).not.toBe(b); expect(b).not.toBe(c); expect(c).not.toContain("private-value");
  values.set("spark-connection-mode", "remote"); values.set("spark-remote-base-url", "https://fixture.example");
  expect(referenceScope()).not.toBe(c);
});
function browserClock() {
  vi.useFakeTimers(); vi.setSystemTime(1_000);
  const host = new EventTarget();
  const doc = Object.assign(new EventTarget(), { visibilityState: "visible" });
  const network = { onLine: true };
  vi.stubGlobal("window", Object.assign(host, { setInterval, clearInterval }));
  vi.stubGlobal("document", doc); vi.stubGlobal("navigator", network);
  return { host, doc, network };
}
it("coalesces focus/reconnect bursts, pauses hidden/offline reads and reconciles recovery", async () => {
  const { host, doc, network } = browserClock();
  setSidebarPreferenceScope("SP05-lifecycle");
  const loader = vi.fn().mockResolvedValue("fresh");
  const stop = observeReferenceRefresh("cron", () => { void referenceResources.read("cron", loader); });
  await vi.advanceTimersByTimeAsync(0);
  host.dispatchEvent(new Event("focus"));
  referenceResources.refresh("cron", true); // existing bus.reconnected callback
  host.dispatchEvent(new Event("focus"));
  await vi.advanceTimersByTimeAsync(50);
  expect(loader).toHaveBeenCalledTimes(2);
  doc.visibilityState = "hidden";
  await vi.advanceTimersByTimeAsync(180_000);
  expect(loader).toHaveBeenCalledTimes(2);
  doc.visibilityState = "visible"; network.onLine = false;
  host.dispatchEvent(new Event("focus"));
  await vi.advanceTimersByTimeAsync(60_000);
  expect(loader).toHaveBeenCalledTimes(2);
  network.onLine = true; host.dispatchEvent(new Event("online"));
  await vi.advanceTimersByTimeAsync(50);
  expect(loader).toHaveBeenCalledTimes(3);
  stop();
});
it("records literal five-minute idle baseline/candidate counts with unchanged 70% budget", async () => {
  browserClock(); setSidebarPreferenceScope("SP05-idle");
  // Same visible sidebar + Cron page: baseline each polls at 15s, plus initial reads.
  let baseline = 2;
  const before = setInterval(() => { baseline += 2; }, 15_000);
  let candidate = 0;
  const stops = (["sidebar", "cron"] as const).map((id) => observeReferenceRefresh(id, () => {
    void referenceResources.read(id, async () => { candidate += 1; return []; });
  }));
  await vi.advanceTimersByTimeAsync(300_050);
  clearInterval(before); stops.forEach((stop) => stop());
  console.log(JSON.stringify({ visibleIdleMs: 300_000, baseline, candidate, reduction: 1 - candidate / baseline }));
  expect(baseline).toBe(42); expect(candidate).toBe(12);
  expect(1 - candidate / baseline).toBeGreaterThanOrEqual(0.70);
});
