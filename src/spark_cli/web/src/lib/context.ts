import { getDashboardToken } from "@/lib/api";

export type ContextScope = "one_turn" | "pinned";

export type InclusionMode = "path_only" | "excerpt" | "summary" | "full" | "search";

export type ContextItemType = "file" | "excerpt" | "note" | "tool_output" | "url";

export interface ContextItem {
  id: string;
  type: ContextItemType;
  source_path?: string | null;
  inclusion_mode: InclusionMode;
  content?: string | null;
  content_ref?: string | null;
  scope: ContextScope;
  size_bytes: number;
  excerpt_range?: [number, number] | null;
  search_query?: string | null;
  label?: string | null;
}

export interface ContextBucket {
  label: string;
  tokens: number;
  items: string[];
}

export interface ContextEstimate {
  prompt_tokens: number;
  attached_tokens: number;
  pinned_tokens: number;
  history_tokens: number;
  total_tokens: number;
  context_window: number;
  utilization: number;
  warning: string | null;
  buckets: ContextBucket[];
}

function authHeaders(): Headers {
  const h = new Headers({ "Content-Type": "application/json" });
  const tok = getDashboardToken();
  if (tok) h.set("Authorization", `Bearer ${tok}`);
  return h;
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { ...init, headers: authHeaders() });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

export const contextApi = {
  listItems: (sessionId: string) =>
    fetchJSON<{ items: ContextItem[] }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/context`,
    ),

  upsertItem: (sessionId: string, item: ContextItem) =>
    fetchJSON<{ ok: boolean; item: ContextItem }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/context/${encodeURIComponent(item.id)}`,
      { method: "PUT", body: JSON.stringify(item) },
    ),

  removeItem: (sessionId: string, itemId: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/context/${encodeURIComponent(itemId)}`,
      { method: "DELETE" },
    ),

  estimateTokens: (params: {
    sessionId?: string;
    promptText: string;
    contextItems: ContextItem[];
  }) =>
    fetchJSON<ContextEstimate>("/api/estimate-tokens", {
      method: "POST",
      body: JSON.stringify({
        session_id: params.sessionId ?? null,
        prompt_text: params.promptText,
        context_items: params.contextItems,
      }),
    }),
};

let _nextId = 0;
export function newContextItemId(): string {
  return `ci_${Date.now()}_${++_nextId}`;
}

export function makeFileContextItem(
  path: string,
  sizeBytes = 0,
  mode: InclusionMode = "full",
): ContextItem {
  return {
    id: newContextItemId(),
    type: "file",
    source_path: path,
    inclusion_mode: mode,
    scope: "one_turn",
    size_bytes: sizeBytes,
    label: path.split("/").pop() ?? path,
  };
}
