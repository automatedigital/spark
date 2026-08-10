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
  getModelInfo: () => fetchJSON<ModelInfoResponse>("/api/model/info"),
  getModelStatus: () => fetchJSON<ModelStatusResponse>("/api/model/status"),
  getModelSuggestions: () => fetchJSON<ModelSuggestionsResponse>("/api/model/suggestions"),
  getAvailableModels: (provider: string, baseUrl?: string) =>
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
  getConversationModels: () =>
    fetchJSON<ConversationModelsResponse>("/api/conversations/models"),
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
