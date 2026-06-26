import { describe, expect, it } from "vitest";
import { createModelApi, type FetchJSON } from "./model";

function recorder() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchJSON = (async <T>(url: string, init?: RequestInit): Promise<T> => {
    calls.push({ url, init });
    return {} as T;
  }) satisfies FetchJSON;
  return { api: createModelApi(fetchJSON), calls };
}

describe("model api client", () => {
  it("keeps model read endpoints on their existing paths", async () => {
    const { api, calls } = recorder();

    await api.getModelInfo();
    await api.getModelStatus();
    await api.getModelSuggestions();
    await api.getReasoningEffort();
    await api.getCodexUsage();

    expect(calls.map((call) => call.url)).toEqual([
      "/api/model/info",
      "/api/model/status",
      "/api/model/suggestions",
      "/api/model/reasoning",
      "/api/model/codex-usage",
    ]);
  });

  it("encodes provider and base url when listing available models", async () => {
    const { api, calls } = recorder();

    await api.getAvailableModels("open router", "http://localhost:11434/a b");

    expect(calls[0]?.url).toBe(
      "/api/model/available?provider=open%20router&base_url=http%3A%2F%2Flocalhost%3A11434%2Fa%20b",
    );
  });

  it("preserves model mutation methods and JSON bodies", async () => {
    const { api, calls } = recorder();

    await api.setSmartModel("anthropic/claude-opus-4.6");
    await api.setFastModel("openai/gpt-5-mini");
    await api.setReasoningEffort("medium");

    expect(calls).toEqual([
      {
        url: "/api/model/smart",
        init: {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: "anthropic/claude-opus-4.6" }),
        },
      },
      {
        url: "/api/model/fast",
        init: {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model: "openai/gpt-5-mini" }),
        },
      },
      {
        url: "/api/model/reasoning",
        init: {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ effort: "medium" }),
        },
      },
    ]);
  });
});
