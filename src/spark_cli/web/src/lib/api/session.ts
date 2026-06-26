import type {
  ConversationModelsResponse,
  PaginatedSessions,
  SessionMessagesResponse,
  SessionSearchResponse,
} from "../api";
import type { FetchJSON } from "./model";

export type SseUrlBuilder = (path: string) => string;

export interface TurnStatusResponse {
  session_id: string;
  resolved_session_id: string;
  latest_session_id: string;
  active_turn_session_id: string | null;
  turn_active: boolean;
  status: string | null;
  phase: "idle" | string;
  started_at: number | null;
  last_event_at: number | null;
  interrupt_requested: boolean;
  active_agent_session_id: string | null;
  stream_revision?: number;
  stream_text_chars?: number;
}

export interface StreamSnapshotResponse {
  session_id: string;
  resolved_session_id: string;
  latest_session_id: string;
  active_turn_session_id: string | null;
  turn_active: boolean;
  stream_text: string;
  stream_revision: number;
  stream_text_chars: number;
}

export function createSessionApi(fetchJSON: FetchJSON, sseUrl: SseUrlBuilder) {
  return {
    getSessions: (limit = 20, offset = 0, source?: string) => {
      const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
      if (source) qs.set("source", source);
      return fetchJSON<PaginatedSessions>(`/api/sessions?${qs.toString()}`);
    },
    getSessionMessages: (id: string, limit = 0, beforeId?: string) => {
      const qs = new URLSearchParams();
      if (limit > 0) qs.set("limit", String(limit));
      if (beforeId) qs.set("before_id", beforeId);
      const q = qs.toString();
      return fetchJSON<SessionMessagesResponse>(
        `/api/sessions/${encodeURIComponent(id)}/messages${q ? `?${q}` : ""}`,
      );
    },
    warmSession: (id: string) =>
      fetchJSON<{ ok: boolean; warm: boolean }>(`/api/sessions/${encodeURIComponent(id)}/warm`, {
        method: "POST",
      }),
    getSessionToolResult: (id: string, toolCallId: string) =>
      fetchJSON<{ session_id: string; tool_call_id: string; content: string; tool_name?: string | null }>(
        `/api/sessions/${encodeURIComponent(id)}/tool-results/${encodeURIComponent(toolCallId)}`,
      ),
    getTurnStatus: (id: string) =>
      fetchJSON<TurnStatusResponse>(
        `/api/conversations/${encodeURIComponent(id)}/turn-status`,
      ),
    getStreamSnapshot: (id: string) =>
      fetchJSON<StreamSnapshotResponse>(
        `/api/conversations/${encodeURIComponent(id)}/stream-snapshot`,
      ),
    deleteSession: (id: string) =>
      fetchJSON<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(id)}`, {
        method: "DELETE",
      }),
    renameSession: (id: string, title: string) =>
      fetchJSON<{ ok: boolean; session_id: string; title: string | null }>(
        `/api/sessions/${encodeURIComponent(id)}/title`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title }),
        },
      ),
    searchSessions: (q: string, limit = 20, source?: string) => {
      const qs = new URLSearchParams({ q, limit: String(limit) });
      if (source) qs.set("source", source);
      return fetchJSON<SessionSearchResponse>(`/api/sessions/search?${qs.toString()}`);
    },
    patchSessionKanban: (sessionId: string, status: string) =>
      fetchJSON<{ ok: boolean; session_id: string; status: string }>(
        `/api/sessions/${encodeURIComponent(sessionId)}/kanban`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        },
      ),
    postConversation: (message: string, model?: string, contextItems?: unknown[]) =>
      fetchJSON<{ session_id: string; ok: boolean }>("/api/conversations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, model, context_items: contextItems ?? [] }),
      }),
    postConversationMessage: (sessionId: string, message: string, contextItems?: unknown[]) =>
      fetchJSON<{ session_id: string; ok: boolean }>(
        `/api/conversations/${encodeURIComponent(sessionId)}/messages`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message, context_items: contextItems ?? [] }),
        },
      ),
    getConversationStream: (sessionId: string): EventSource =>
      new EventSource(sseUrl(`/api/conversations/${encodeURIComponent(sessionId)}/stream`)),
    getConversationModels: () =>
      fetchJSON<ConversationModelsResponse>("/api/conversations/models"),
    interruptConversation: (sessionId: string, message?: string) =>
      fetchJSON<{ ok: boolean; session_id: string }>(
        `/api/conversations/${encodeURIComponent(sessionId)}/interrupt`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: message ?? null }),
        },
      ),
    switchConversationModel: (sessionId: string, model: string) =>
      fetchJSON<{ ok: boolean; session_id: string; model: string }>(
        `/api/conversations/${encodeURIComponent(sessionId)}/model`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model }),
        },
      ),
    forkConversation: (sessionId: string, fromMessageIndex?: number) =>
      fetchJSON<{ ok: boolean; session_id: string; source_session_id: string }>(
        `/api/conversations/${encodeURIComponent(sessionId)}/fork`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ from_message_index: fromMessageIndex ?? null }),
        },
      ),
    getSessionForks: (sessionId: string) =>
      fetchJSON<{
        forks: Array<{ id: string; title: string }>;
        fork_count: number;
        parent_session_id: string | null;
        parent_title: string | null;
      }>(`/api/sessions/${encodeURIComponent(sessionId)}/forks`),
    retryConversation: (sessionId: string, messageIndex: number, message?: string) =>
      fetchJSON<{ ok: boolean; session_id: string }>(
        `/api/conversations/${encodeURIComponent(sessionId)}/retry`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_index: messageIndex, message: message ?? null }),
        },
      ),
    submitConversationApproval: (
      sessionId: string,
      choice: "once" | "session" | "always" | "deny",
      resolveAll = false,
    ) =>
      fetchJSON<{ ok: boolean; session_id: string; resolved: number }>(
        `/api/conversations/${encodeURIComponent(sessionId)}/approval`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ choice, resolve_all: resolveAll }),
        },
      ),
    submitFeedback: (
      sessionId: string,
      data: { name: string; email: string; area: string; note: string },
    ) =>
      fetchJSON<{ ok: boolean }>(
        `/api/conversations/${encodeURIComponent(sessionId)}/feedback`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(data),
        },
      ),
  };
}

export type SessionApi = ReturnType<typeof createSessionApi>;
