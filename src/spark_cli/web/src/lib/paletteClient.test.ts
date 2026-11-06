import { afterEach, expect, it, vi } from "vitest";
import { cachedPaletteRecent, readPalette } from "./paletteClient";
import { setSidebarPreferenceScope } from "./sidebarPrefs";
import { setDashboardToken } from "./apiHelpers";

afterEach(() => vi.unstubAllGlobals());
const page = { items: [{ kind: "thread", id: "one", label: "Recent", description: "" }], next: null };

it("uses one bounded authenticated recent read and retains a scoped snapshot", async () => {
  vi.stubGlobal("localStorage", { getItem: () => null });
  setSidebarPreferenceScope("palette-test-one");
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(page)));
  vi.stubGlobal("fetch", fetch);
  const controller = new AbortController();
  expect(await readPalette("recent", "", controller.signal)).toEqual(page);
  expect(fetch.mock.calls[0][0]).toBe("/api/palette/recent?q=&limit=12&offset=0");
  expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
  expect(cachedPaletteRecent()).toEqual(page);
  setSidebarPreferenceScope("palette-test-two");
  expect(cachedPaletteRecent()).toBeUndefined();
});

it.each(["abort", "profile", "auth"])("rejects a late %s response without caching it", async (kind) => {
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: vi.fn() });
  setSidebarPreferenceScope(`start-${kind}`);
  let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((done) => { resolve = done; })));
  const controller = new AbortController();
  const request = readPalette("recent", "", controller.signal);
  if (kind === "abort") controller.abort();
  if (kind === "profile") setSidebarPreferenceScope("replacement");
  if (kind === "auth") setDashboardToken("replacement");
  resolve(new Response(JSON.stringify(page)));
  await expect(request).rejects.toThrow();
  expect(cachedPaletteRecent()).toBeUndefined();
});

it("fences A to B to A even when the final backend URL matches", async () => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) });
  const { setRemoteConnection, setLocalConnection } = await import("./apiHelpers");
  setLocalConnection();
  setSidebarPreferenceScope("backend-aba");
  let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((done) => { resolve = done; })));
  const request = readPalette("recent", "", new AbortController().signal);
  setRemoteConnection("http://fixture.invalid", "fixture-token");
  setLocalConnection();
  resolve(new Response(JSON.stringify(page)));
  await expect(request).rejects.toThrow();
  expect(cachedPaletteRecent()).toBeUndefined();
});
