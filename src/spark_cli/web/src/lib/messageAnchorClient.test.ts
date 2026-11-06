import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { readMessageWindow } from "./messageAnchorClient";
import { setGlobalNavTarget, takeGlobalNavTarget, takeMessageAnchor } from "./globalNavigation";
import { setSidebarPreferenceScope } from "./sidebarPrefs";

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) });
  vi.stubGlobal("window", new EventTarget());
  vi.stubGlobal("CustomEvent", class extends Event { detail: unknown; constructor(name: string, options: { detail: unknown }) { super(name); this.detail = options.detail; } });
  setSidebarPreferenceScope("anchor-test");
});
afterEach(() => vi.unstubAllGlobals());

it("retains exact identity after shell target consumption, only for its thread", () => {
  setGlobalNavTarget({ type: "thread", id: "thread-one", messageId: "5001" });
  expect(takeGlobalNavTarget("thread")?.messageId).toBe("5001");
  expect(takeMessageAnchor("thread-two")).toBeNull();
  expect(takeMessageAnchor("thread-one")).toBe("5001");
  expect(takeMessageAnchor("thread-one")).toBeNull();
});
it("does not reuse an anchor across profile changes or a later ordinary navigation", () => {
  setGlobalNavTarget({ type: "thread", id: "same-id", messageId: "5001" });
  setSidebarPreferenceScope("other-profile");
  expect(takeMessageAnchor("same-id")).toBeNull();
  setGlobalNavTarget({ type: "thread", id: "same-id", messageId: "5001" });
  setGlobalNavTarget({ type: "thread", id: "same-id" });
  expect(takeMessageAnchor("same-id")).toBeNull();
});
it("uses bounded encoded reads and passes cancellation with stable directional cursors", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ messages: [] })));
  vi.stubGlobal("fetch", fetch);
  const signal = new AbortController().signal;
  await readMessageWindow("thread/?'", "5001", signal, { after_id: 5025 });
  expect(fetch.mock.calls[0][0]).toBe("/api/sessions/thread%2F%3F'/message-window/5001?limit=50&after_id=5025");
  expect(fetch.mock.calls[0][1].signal).toBe(signal);
});
