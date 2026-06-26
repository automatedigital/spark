import type {
  ModelInfoResponse,
  ModelStatusResponse,
  ModelSuggestionsResponse,
  ReasoningEffortResponse,
} from "../api";

export type FetchJSON = <T>(url: string, init?: RequestInit) => Promise<T>;

export function createModelApi(fetchJSON: FetchJSON) {
  return {
    getModelInfo: () => fetchJSON<ModelInfoResponse>("/api/model/info"),
    getModelStatus: () => fetchJSON<ModelStatusResponse>("/api/model/status"),
    getModelSuggestions: () => fetchJSON<ModelSuggestionsResponse>("/api/model/suggestions"),
    getAvailableModels: (provider: string, baseUrl?: string) =>
      fetchJSON<{ provider: string; models: string[]; live: boolean; strict: boolean }>(
        `/api/model/available?provider=${encodeURIComponent(provider)}` +
          (baseUrl ? `&base_url=${encodeURIComponent(baseUrl)}` : ""),
      ),
    setSmartModel: (model: string) =>
      fetchJSON<{ ok: boolean; model: string }>("/api/model/smart", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model }),
      }),
    setFastModel: (model: string) =>
      fetchJSON<{ ok: boolean; model: string }>("/api/model/fast", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model }),
      }),
    getReasoningEffort: () => fetchJSON<ReasoningEffortResponse>("/api/model/reasoning"),
    setReasoningEffort: (effort: string) =>
      fetchJSON<{ effort: string; ok: boolean }>("/api/model/reasoning", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ effort }),
      }),
    getCodexUsage: () =>
      fetchJSON<{ available: boolean; reason?: string; data?: Record<string, unknown> }>(
        "/api/model/codex-usage",
      ),
  };
}

export type ModelApi = ReturnType<typeof createModelApi>;
