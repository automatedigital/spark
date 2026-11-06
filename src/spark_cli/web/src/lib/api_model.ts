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
