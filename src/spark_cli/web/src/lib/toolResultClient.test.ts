import { afterEach, describe, expect, it, vi } from "vitest";
import { readToolResult, type ToolResultPage } from "./toolResultClient";

afterEach(() => vi.unstubAllGlobals());
describe("tool result domain reader", () => {
  it("uses explicit bounded pages, scoped IDs, revision and native cancellation", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ content: "page" }) });
    vi.stubGlobal("fetch", fetcher);
    const controller = new AbortController();
    await readToolResult("thread/one", "call/two", controller.signal);
    expect(fetcher.mock.calls[0][0]).toBe("/api/sessions/thread%2Fone/tool-results/call%2Ftwo?paged=true&offset=0");
    expect(fetcher.mock.calls[0][1].signal).toBe(controller.signal);
    await readToolResult("thread/one", "call/two", controller.signal, { next_offset: 65533, revision: "rev" } as ToolResultPage);
    expect(fetcher.mock.calls[1][0]).toContain("offset=65533&revision=rev");
    controller.abort();
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
  });
});
