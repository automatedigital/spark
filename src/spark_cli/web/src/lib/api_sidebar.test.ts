import { afterEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_SIDEBAR_METADATA, SidebarMutationError, sidebarApi } from "./api_sidebar";

afterEach(() => vi.unstubAllGlobals());
function respond(body: unknown, status = 200) {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
describe("sidebar metadata API", () => {
  it("uses the existing dashboard auth transport and encodes exact session IDs", async () => {
    vi.stubGlobal("localStorage", { getItem: (key: string) => key === "spark_dashboard_token" ? "fixture-token" : null });
    const fetch = respond({ schema_version: 1, metadata: DEFAULT_SIDEBAR_METADATA });
    await sidebarApi.patchSidebarThread("exact/id", 3, { pinned: true });
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe("/api/sidebar/threads/exact%2Fid");
    expect(init.headers.get("Authorization")).toBe("Bearer fixture-token");
    expect(JSON.parse(init.body)).toEqual({ expected_revision: 3, pinned: true });
  });
  it("exposes the current revision on a conflict without retrying the gesture", async () => {
    const current = { ...DEFAULT_SIDEBAR_METADATA, pinned: true, revision: 4 };
    const fetch = respond({ detail: "Metadata changed", current }, 409);
    try {
      await sidebarApi.patchSidebarThread("a", 3, { settled: true });
      throw new Error("Expected a conflict");
    } catch (error) {
      expect(error).toBeInstanceOf(SidebarMutationError);
      expect((error as SidebarMutationError).current).toEqual(current);
    }
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("makes an unavailable router recoverable even if a SPA catch-all returns HTML", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<!doctype html>")));
    await expect(sidebarApi.getSidebarThreads()).rejects.toThrow("Thread organization is unavailable");
  });
});
