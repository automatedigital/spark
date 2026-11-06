import { beforeEach, expect, it, vi } from "vitest";
import { ModelListLoader, MODEL_LIST_TTL, invalidateModelCredentials, type ModelListState } from "./modelListLoader";
import { setDashboardToken, setRemoteConnection } from "./apiHelpers";
import { setSidebarPreferenceScope } from "./sidebarPrefs";

const result = (models: string[]) => ({ provider: "fixture", models, live: true, strict: false, source: "fixture", warning: "" });
function deferred() {
  let resolve!: (value: ReturnType<typeof result>) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<ReturnType<typeof result>>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  invalidateModelCredentials();
  const storage = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value) });
});

it.each([
  ["provider-a", "http://same.invalid", "provider-b", "http://same.invalid"],
  ["route", "http://a.invalid", "route", "http://b.invalid"],
])("fences deferred reverse completion from %s at %s", async (providerA, urlA, providerB, urlB) => {
  const a = deferred(), b = deferred();
  const updatesA: ModelListState[] = [], updatesB: ModelListState[] = [];
  const requestA = vi.fn(() => a.promise);
  const loaderA = new ModelListLoader(providerA, urlA, s => updatesA.push(s), requestA);
  const pendingA = loaderA.load(true);
  loaderA.cancel();
  const loaderB = new ModelListLoader(providerB, urlB, s => updatesB.push(s), () => b.promise);
  const pendingB = loaderB.load(true);
  b.resolve(result(["b"])); await pendingB;
  a.resolve(result(["a"])); await pendingA;
  expect(updatesA.map(s => s.phase)).toEqual(["loading"]);
  expect(updatesB.at(-1)?.models).toEqual(["b"]);
  expect((requestA.mock.calls as unknown as [string, string, AbortSignal][])[0][2].aborted).toBe(true);
});

it.each(["token", "credential", "profile", "backend", "storage-token"])("rejects late %s epoch responses and does not cache them", async kind => {
  const pending = deferred();
  const updates: ModelListState[] = [];
  const loader = new ModelListLoader("custom", "http://a.invalid", s => updates.push(s), () => pending.promise);
  const task = loader.load();
  if (kind === "storage-token") localStorage.setItem("spark_dashboard_token", "synthetic-storage-token");
  if (kind === "backend") setRemoteConnection("http://other-backend.invalid", "synthetic-token");
  if (kind === "token") setDashboardToken("synthetic-new-token");
  if (kind === "credential") invalidateModelCredentials();
  if (kind === "profile") setSidebarPreferenceScope("fixture-new-profile");
  pending.resolve(result(["retired"])); await task;
  expect(updates.map(s => s.phase)).toEqual(["loading"]);
  expect(new ModelListLoader("custom", "http://a.invalid", () => {}).snapshot().phase).toBe("idle");
});

it("uses bounded TTL memory entries, reopening makes no call and explicit Refresh bypasses", async () => {
  let now = 0;
  const request = vi.fn(async () => result(["model"]));
  const loader = new ModelListLoader("custom", "http://a.invalid", () => {}, request, () => now);
  await loader.load();
  const reopened = new ModelListLoader("custom", "http://a.invalid", () => {}, request, () => now);
  expect(reopened.snapshot().phase).toBe("ready");
  await reopened.load(); expect(request).toHaveBeenCalledTimes(1);
  await reopened.load(true); expect(request).toHaveBeenCalledTimes(2);
  now += MODEL_LIST_TTL;
  expect(reopened.snapshot().phase).toBe("stale");
  await reopened.load(); expect(request).toHaveBeenCalledTimes(3);
  for (let i = 0; i < 17; i++) await new ModelListLoader("custom", `http://${i}.invalid`, () => {}, request).load();
  expect(loader.snapshot().phase).toBe("idle");
});

it("distinguishes empty/error, retains cached choices on failure and retries", async () => {
  const states: ModelListState[] = [];
  const request = vi.fn().mockResolvedValueOnce(result(["custom-id"])).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(result([]));
  const loader = new ModelListLoader("custom", "", s => states.push(s), request);
  await loader.load(true); await loader.load(true);
  expect(states.at(-1)).toEqual({ phase: "error", models: ["custom-id"], live: true });
  await loader.load(true); expect(states.at(-1)?.phase).toBe("empty");
});

it("bounds and deduplicates response model IDs", async () => {
  const loader = new ModelListLoader("custom", "", () => {}, async () => result([...Array.from({length: 600}, (_, i) => `${i}`), "0"]));
  await loader.load(); expect(loader.snapshot().models).toHaveLength(500);
});

it("retry aborts the old attempt and a late failure cannot overwrite success", async () => {
  const old = deferred();
  const states: ModelListState[] = [];
  const request = vi.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce(result(["retry"]));
  const loader = new ModelListLoader("custom", "", s => states.push(s), request);
  const first = loader.load(true);
  await loader.load(true);
  old.reject(new Error("retired offline")); await first;
  expect(states.at(-1)?.models).toEqual(["retry"]);
  expect(request.mock.calls[0][2].aborted).toBe(true);
});
