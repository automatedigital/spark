/** session endpoints, split out of api.ts. */

import {
  fetchJSON,
  withDashboardOrSessionToken,
} from "./apiHelpers";
import type {
  OAuthPollResponse,
  PaginatedSessions,
  SessionInfo,
  SessionMessagesResponse,
  SessionSearchResponse,
} from "./apiTypes";

export const sessionApi = {
  getSessions: (limit = 20, offset = 0, source?: string) => {
    const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (source) qs.set("source", source);
    return fetchJSON<PaginatedSessions>(`/api/sessions?${qs.toString()}`);
  },
  getSession: (id: string) =>
    fetchJSON<Partial<SessionInfo> & { id: string }>(`/api/sessions/${encodeURIComponent(id)}`),
  getSessionMessages: (id: string, limit = 0, beforeId?: string) => {
    const qs = new URLSearchParams();
    if (limit > 0) qs.set("limit", String(limit));
    const rawBeforeId = beforeId?.startsWith("db:") ? beforeId.slice(3) : beforeId;
    if (rawBeforeId) qs.set("before_id", rawBeforeId);
    qs.set("_", String(Date.now()));
    const q = qs.toString();
    return fetchJSON<SessionMessagesResponse>(
      `/api/sessions/${encodeURIComponent(id)}/messages${q ? `?${q}` : ""}`,
    );
  },
  moveSession: (id: string, source: string | null) =>
    fetchJSON<{ ok: boolean; session_id: string; source: string | null; session?: SessionInfo }>(
      `/api/sessions/${encodeURIComponent(id)}/source`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source }),
      },
    ),
  warmSession: (id: string) =>
    fetchJSON<{ ok: boolean; warm: boolean }>(`/api/sessions/${encodeURIComponent(id)}/warm`, {
      method: "POST",
    }),
  getSessionToolResult: (id: string, toolCallId: string) =>
    fetchJSON<{ session_id: string; tool_call_id: string; content: string; tool_name?: string | null }>(
      `/api/sessions/${encodeURIComponent(id)}/tool-results/${encodeURIComponent(toolCallId)}`,
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

  // Kanban status management
  getSessionForks: (sessionId: string) =>
    fetchJSON<{
      forks: Array<{ id: string; title: string }>;
      fork_count: number;
      parent_session_id: string | null;
      parent_title: string | null;
    }>(`/api/sessions/${encodeURIComponent(sessionId)}/forks`),
  pollOAuthSession: (providerId: string, sessionId: string) =>
    fetchJSON<OAuthPollResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/poll/${encodeURIComponent(sessionId)}`,
    ),
  cancelOAuthSession: (sessionId: string) =>
    withDashboardOrSessionToken((authHeader) =>
      fetchJSON<{ ok: boolean }>(
        `/api/providers/oauth/sessions/${encodeURIComponent(sessionId)}`,
        {
          method: "DELETE",
          headers: authHeader,
        },
      ),
    ),
};
