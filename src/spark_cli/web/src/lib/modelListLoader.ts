import { apiConnectionGeneration, getApiBase, getDashboardToken } from "./apiHelpers";
import { sidebarPreferenceKey, sidebarPreferenceScopeGeneration } from "./sidebarPrefs";
import { modelApi } from "./api_model";

export const MODEL_LIST_TTL = 30_000;
const MAX_ENTRIES = 16;
const MAX_MODELS = 500;
const cache = new Map<string, { models: string[]; at: number; live: boolean }>();
let credentialEpoch = 0;
let transportAuthEpoch = 0;
let observedToken: string | null | undefined;
const listeners = new Set<() => void>();
export const modelCredentialEpoch = () => credentialEpoch;
export function subscribeModelCredentials(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function invalidateModelCredentials() {
  credentialEpoch++;
  cache.clear();
  for (const listener of listeners) listener();
}
export function modelListScope(provider: string, baseUrl: string) {
  // Also fence cross-tab storage changes that bypass the connection setters.
  const token = getDashboardToken();
  if (token !== observedToken) {
    observedToken = token;
    transportAuthEpoch++;
    cache.clear();
  }
  return JSON.stringify([provider, baseUrl, getApiBase(), apiConnectionGeneration(),
    sidebarPreferenceKey("model-list"), sidebarPreferenceScopeGeneration(), credentialEpoch, transportAuthEpoch]);
}
export type ModelListState = {
  models: string[];
  phase: "idle" | "loading" | "ready" | "stale" | "empty" | "error";
  live: boolean;
};

/** Per-mounted consumer ownership; cache contains IDs only, never credentials. */
export class ModelListLoader {
  private controller?: AbortController;
  private generation = 0;
  private readonly scope: string;
  private provider: string;
  private baseUrl: string;
  private publish: (state: ModelListState) => void;
  private request: typeof modelApi.getAvailableModels;
  private now: () => number;
  constructor(provider: string, baseUrl: string,
    publish: (state: ModelListState) => void,
    request = modelApi.getAvailableModels,
    now = () => Date.now()) {
    this.provider = provider;
    this.baseUrl = baseUrl;
    this.publish = publish;
    this.request = request;
    this.now = now;
    this.scope = modelListScope(provider, baseUrl);
  }
  snapshot(): ModelListState {
    const entry = this.scope === modelListScope(this.provider, this.baseUrl) ? cache.get(this.scope) : undefined;
    if (!entry) return { models: [], phase: "idle", live: false };
    return { models: entry.models, live: entry.live,
      phase: this.now() - entry.at >= MODEL_LIST_TTL ? "stale" : entry.models.length ? "ready" : "empty" };
  }
  cancel() { this.generation++; this.controller?.abort(); }
  async load(refresh = false) {
    if (!this.provider || this.scope !== modelListScope(this.provider, this.baseUrl)) return;
    const cached = this.snapshot();
    if (!refresh && cached.phase !== "idle" && cached.phase !== "stale") {
      this.publish(cached);
      return;
    }
    this.cancel();
    const generation = this.generation;
    const controller = new AbortController();
    this.controller = controller;
    const current = () => generation === this.generation && !controller.signal.aborted &&
      this.scope === modelListScope(this.provider, this.baseUrl);
    this.publish({ ...cached, phase: "loading" });
    try {
      const result = await this.request(this.provider, this.baseUrl || undefined, controller.signal);
      if (!current()) return;
      const models = [...new Set(result.models.filter((id) => typeof id === "string" && id.length <= 1024))].slice(0, MAX_MODELS);
      cache.delete(this.scope);
      cache.set(this.scope, { models, at: this.now(), live: result.live });
      while (cache.size > MAX_ENTRIES) cache.delete(cache.keys().next().value!);
      this.publish({ models, live: result.live, phase: models.length ? "ready" : "empty" });
    } catch {
      if (current()) this.publish({ ...cached, phase: "error" });
    }
  }
}
