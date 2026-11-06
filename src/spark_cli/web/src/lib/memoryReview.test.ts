import { afterEach, expect, it, vi } from "vitest";
import { memoryReview } from "./memoryReview";
import { setSidebarPreferenceScope } from "./sidebarPrefs";

afterEach(() => vi.unstubAllGlobals());
it("uses one abortable targets read and encodes literal search", async () => {
  vi.stubGlobal("localStorage", { getItem: () => null });
  const fetch = vi.fn().mockImplementation(async () => new Response('{"targets":{}}'));
  vi.stubGlobal("fetch", fetch);
  const controller = new AbortController();
  await memoryReview.targets(controller.signal);
  expect(fetch.mock.calls[0][0]).toBe("/api/memory");
  expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
  await memoryReview.facts("% &", 20, controller.signal);
  expect(fetch.mock.calls[1][0]).toBe("/api/memory/facts?q=%25+%26&after=20");
});
it.each(["abort", "profile"])("rejects late %s responses", async (kind) => {
  vi.stubGlobal("localStorage", { getItem: () => null });
  setSidebarPreferenceScope("memory-start");
  let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((done) => { resolve = done; })));
  const controller = new AbortController();
  const request = memoryReview.targets(controller.signal);
  if (kind === "abort") controller.abort();
  else setSidebarPreferenceScope("memory-other");
  resolve(new Response('{"targets":{}}'));
  await expect(request).rejects.toThrow();
});
