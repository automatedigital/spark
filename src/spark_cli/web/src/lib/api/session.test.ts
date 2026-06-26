import { describe, expect, it, vi } from "vitest";
import { createSessionApi } from "./session";
import type { FetchJSON } from "./model";

function recorder() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchJSON = (async <T>(url: string, init?: RequestInit): Promise<T> => {
    calls.push({ url, init });
    return {} as T;
  }) satisfies FetchJSON;
  const sseUrl = vi.fn((path: string) => `/sse${path}`);
  return { api: createSessionApi(fetchJSON, sseUrl), calls, sseUrl };
}

describe("session api client", () => {
  it("keeps session read endpoints on their existing paths", async () => {
    const { api, calls } = recorder();

    await api.getSessions(10, 20, "web");
    await api.getSessionMessages("session 1", 50, "msg/2");
    await api.getTurnStatus("session 1");
    await api.getStreamSnapshot("session 1");
    await api.getSessionToolResult("session 1", "tool/1");

    expect(calls.map((call) => call.url)).toEqual([
      "/api/sessions?limit=10&offset=20&source=web",
      "/api/sessions/session%201/messages?limit=50&before_id=msg%2F2",
      "/api/conversations/session%201/turn-status",
      "/api/conversations/session%201/stream-snapshot",
      "/api/sessions/session%201/tool-results/tool%2F1",
    ]);
  });

  it("preserves conversation mutation methods and JSON bodies", async () => {
    const { api, calls } = recorder();

    await api.postConversation("hello", "model/a", [{ path: "x" }]);
    await api.postConversationMessage("session 1", "next");
    await api.interruptConversation("session 1", "stop");
    await api.retryConversation("session 1", 3, "edited");
    await api.submitConversationApproval("session 1", "once", true);

    expect(calls).toEqual([
      {
        url: "/api/conversations",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: "hello", model: "model/a", context_items: [{ path: "x" }] }),
        },
      },
      {
        url: "/api/conversations/session%201/messages",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: "next", context_items: [] }),
        },
      },
      {
        url: "/api/conversations/session%201/interrupt",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: "stop" }),
        },
      },
      {
        url: "/api/conversations/session%201/retry",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_index: 3, message: "edited" }),
        },
      },
      {
        url: "/api/conversations/session%201/approval",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ choice: "once", resolve_all: true }),
        },
      },
    ]);
  });

  it("builds conversation event streams through the shared sse url helper", () => {
    const { api, sseUrl } = recorder();
    const OriginalEventSource = globalThis.EventSource;
    const eventSource = vi.fn();
    globalThis.EventSource = eventSource as unknown as typeof EventSource;

    try {
      api.getConversationStream("session 1");
    } finally {
      globalThis.EventSource = OriginalEventSource;
    }

    expect(sseUrl).toHaveBeenCalledWith("/api/conversations/session%201/stream");
    expect(eventSource).toHaveBeenCalledWith("/sse/api/conversations/session%201/stream");
  });
});
