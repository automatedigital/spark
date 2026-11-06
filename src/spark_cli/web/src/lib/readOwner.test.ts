import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ReadOwner } from "./readOwner";
import { setDashboardToken, setRemoteConnection } from "./apiHelpers";
import { setSidebarPreferenceScope } from "./sidebarPrefs";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  });
  vi.stubGlobal("window", new EventTarget());
});
afterEach(() => vi.unstubAllGlobals());

it("fences deferred A-B-A success, late errors and finally without sharing read controllers", async () => {
  let generation = 1;
  const a = new ReadOwner(() => generation === 1);
  const first = deferred<string>(), second = deferred<string>();
  const signals: AbortSignal[] = [];
  let loading = "old", content = "", error = "";
  const old = a.read(signal => { signals.push(signal); return first.promise; })
    .then(value => { if (a.isCurrent()) content = value; })
    .catch(reason => { if (a.isCurrent()) error = String(reason); })
    .finally(() => { if (a.isCurrent()) loading = ""; });
  const independent = a.read(signal => { signals.push(signal); return second.promise; });
  const rejected = expect(independent).rejects.toMatchObject({ name: "AbortError" });
  expect(signals[0]).not.toBe(signals[1]);
  generation = 2; a.retire();
  generation = 3;
  const nextA = new ReadOwner(() => generation === 3);
  loading = "replacement";
  first.resolve("obsolete A"); second.reject(new Error("late network failure"));
  await Promise.all([old, rejected]);
  expect(signals.every(signal => signal.aborted)).toBe(true);
  expect({ loading, content, error }).toEqual({ loading: "replacement", content: "", error: "" });
  expect(await nextA.read(async () => "new A")).toBe("new A");
  nextA.retire();
});

it.each(["backend", "credential", "profile", "unmount"])("retires same-ID reads on %s replacement", async kind => {
  const owner = new ReadOwner(() => true);
  const pending = deferred<string>();
  let signal!: AbortSignal;
  const result = owner.read(value => { signal = value; return pending.promise; });
  const rejected = expect(result).rejects.toMatchObject({ name: "AbortError" });
  if (kind === "backend") setRemoteConnection("https://other.example", "");
  if (kind === "credential") setDashboardToken("replacement");
  if (kind === "profile") setSidebarPreferenceScope("replacement");
  if (kind === "unmount") owner.retire();
  expect(signal.aborted).toBe(true);
  pending.resolve("same session ID from old scope");
  await rejected;
  expect(owner.isCurrent()).toBe(false);
});

it("one settled read does not cancel an independent read or an accepted mutation", async () => {
  const owner = new ReadOwner(() => true);
  const pending = deferred<string>();
  let secondSignal!: AbortSignal;
  const second = owner.read(signal => { secondSignal = signal; return pending.promise; });
  expect(await owner.read(async () => "first")).toBe("first");
  expect(secondSignal.aborted).toBe(false);
  pending.resolve("second");
  expect(await second).toBe("second");
  const acceptedMutation = deferred<string>();
  owner.retire();
  acceptedMutation.resolve("durable acceptance");
  expect(await acceptedMutation.promise).toBe("durable acceptance");
});

it("surfaces a current read failure without retiring independent work", async () => {
  const owner = new ReadOwner(() => true);
  const failure = new Error("current backend unavailable");
  await expect(owner.read(async () => { throw failure; })).rejects.toBe(failure);
  expect(owner.isCurrent()).toBe(true);
  expect(await owner.read(async () => "recovered")).toBe("recovered");
  owner.retire();
});
