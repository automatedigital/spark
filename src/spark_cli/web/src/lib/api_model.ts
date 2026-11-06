/** model endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  ConversationModelsResponse,
  ModelInfoResponse,
  ModelStatusResponse,
  ModelSuggestionsResponse,
} from "./apiTypes";

export const modelApi = {
  getModelInfo: (signal?: AbortSignal) => fetchJSON<ModelInfoResponse>("/api/model/info", { signal }),
  getModelStatus: (signal?: AbortSignal) => fetchJSON<ModelStatusResponse>("/api/model/status", { signal }),
  getModelSuggestions: (signal?: AbortSignal) => fetchJSON<ModelSuggestionsResponse>("/api/model/suggestions", { signal }),
  getAvailableModels: (provider: string, baseUrl?: string, signal?: AbortSignal) =>
    fetchJSON<{
      provider: string;
      models: string[];
      live: boolean;
      strict: boolean;
      source: string;
      warning: string;
    }>(
      `/api/model/available?provider=${encodeURIComponent(provider)}` +
        (baseUrl ? `&base_url=${encodeURIComponent(baseUrl)}` : ""),
      { signal },
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
  getConversationModels: (signal?: AbortSignal) =>
    fetchJSON<ConversationModelsResponse>("/api/conversations/models", { signal }),
  switchConversationModel: (sessionId: string, model: string) =>
    fetchJSON<{ ok: boolean; session_id: string; model: string }>(
      `/api/conversations/${encodeURIComponent(sessionId)}/model`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model }),
      },
    ),
};
