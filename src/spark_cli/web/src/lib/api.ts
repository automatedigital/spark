import {
  CONNECTION_MODE_KEY,
  REMOTE_BASE_URL_KEY,
  normalizeBaseUrl,
  parseConnectionMode,
  resolveApiBase,
  type ConnectionMode,
} from "./connection";

const DASHBOARD_TOKEN_KEY = "spark_dashboard_token";

// ── Connection mode / API base URL ──────────────────────────────────────────
// In "local" mode the UI talks to the same origin it was served from (base "").
// In "remote" mode every request is prefixed with the stored remote base URL so
// the desktop app can drive an existing Spark instance (e.g. a VPS dashboard).
// getApiBase() is the SINGLE SOURCE OF TRUTH for the base URL — fetchJSON, the
// URL builders, and sseUrl all funnel through it.

export function getConnectionMode(): ConnectionMode {
  if (typeof localStorage === "undefined" || typeof localStorage.getItem !== "function") return "local";
  return parseConnectionMode(localStorage.getItem(CONNECTION_MODE_KEY));
}

export function getRemoteBaseUrl(): string | null {
  if (typeof localStorage === "undefined" || typeof localStorage.getItem !== "function") return null;
  return localStorage.getItem(REMOTE_BASE_URL_KEY);
}

/** Effective base URL prepended to every API/SSE/raw-file path ("" = same-origin). */
export function getApiBase(): string {
  return resolveApiBase(getConnectionMode(), getRemoteBaseUrl());
}

/**
 * Switch to a remote instance. Persists mode + normalized base URL and the
 * dashboard token together so they stay in sync. Caller is expected to have
 * already validated the connection (validateRemoteConnection in connection.ts).
 */
export function setRemoteConnection(baseUrl: string, token: string): void {
  localStorage.setItem(CONNECTION_MODE_KEY, "remote");
  localStorage.setItem(REMOTE_BASE_URL_KEY, normalizeBaseUrl(baseUrl) ?? baseUrl.trim().replace(/\/+$/, ""));
  setDashboardToken(token);
}

/** Switch back to the local sidecar: clears remote base + token. */
export function setLocalConnection(): void {
  localStorage.setItem(CONNECTION_MODE_KEY, "local");
  localStorage.removeItem(REMOTE_BASE_URL_KEY);
  clearDashboardToken();
}

// Ephemeral session token for protected endpoints (reveal).
// Fetched once on first reveal request and cached in memory.
let _sessionToken: string | null = null;

export function getDashboardToken(): string | null {
  if (typeof localStorage === "undefined" || typeof localStorage.getItem !== "function") return null;
  return localStorage.getItem(DASHBOARD_TOKEN_KEY);
}

export function setDashboardToken(token: string): void {
  localStorage.setItem(DASHBOARD_TOKEN_KEY, token.trim());
}

export function clearDashboardToken(): void {
  localStorage.removeItem(DASHBOARD_TOKEN_KEY);
}

/** Build a URL for raw-file serving (binary-safe) with auth token as query param.
 *  Use for <img src>, <video src>, and download <a href> where custom headers can't be sent. */
export function workspaceRawFileUrl(slug: string, path: string): string {
  const qs = new URLSearchParams({ path });
  const tok = getDashboardToken();
  if (tok) qs.set("dashboard_token", tok);
  return `${getApiBase()}/api/workspace/projects/${encodeURIComponent(slug)}/raw-file?${qs}`;
}

/** Build a protected URL for MEDIA:/absolute/path attachments in chat output. */
export function mediaFileUrl(path: string): string {
  const qs = new URLSearchParams({ path });
  const tok = getDashboardToken();
  if (tok) qs.set("dashboard_token", tok);
  return `${getApiBase()}/api/media?${qs}`;
}

/** Build a protected URL for downloading one of Spark's known log files. */
export function logsDownloadUrl(file: string): string {
  const qs = new URLSearchParams({ file });
  const tok = getDashboardToken();
  if (tok) qs.set("dashboard_token", tok);
  return `${getApiBase()}/api/logs/download?${qs}`;
}

/** Append dashboard auth for EventSource (no custom headers support). */
export function sseUrl(path: string): string {
  const full = `${getApiBase()}${path}`;
  const t = getDashboardToken();
  if (!t) return full;
  const sep = full.includes("?") ? "&" : "?";
  return `${full}${sep}dashboard_token=${encodeURIComponent(t)}`;
}

function authHeaders(base?: HeadersInit): Headers {
  const h = new Headers(base);
  // Never clobber an Authorization header the caller set explicitly. The
  // OAuth/reveal endpoints authenticate with the per-process *session token*
  // (distinct from the dashboard token); overwriting it with the dashboard
  // token here made those endpoints 401 whenever a dashboard token was set.
  if (!h.has("Authorization")) {
    const tok = getDashboardToken();
    if (tok) h.set("Authorization", `Bearer ${tok}`);
  }
  return h;
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getApiBase()}${url}`, {
    ...init,
    headers: authHeaders(init?.headers),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    const err = new Error(`${res.status}: ${text}`) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function getSessionToken(force = false): Promise<string> {
  if (_sessionToken && !force) return _sessionToken;
  const resp = await fetchJSON<{ token: string }>("/api/auth/session-token");
  _sessionToken = resp.token;
  return _sessionToken;
}

/**
 * Run a request that requires the per-process session token. The token is
 * regenerated whenever the backend restarts, so a cached value can go stale and
 * produce a 401. On a 401 we drop the cached token, refetch it, and retry once
 * before surfacing the error.
 */
async function withSessionToken<T>(run: (token: string) => Promise<T>): Promise<T> {
  const token = await getSessionToken();
  try {
    return await run(token);
  } catch (e) {
    if (e instanceof Error && e.message.startsWith("401")) {
      _sessionToken = null;
      const fresh = await getSessionToken(true);
      return run(fresh);
    }
    throw e;
  }
}

async function withDashboardOrSessionToken<T>(
  run: (headers: HeadersInit) => Promise<T>,
): Promise<T> {
  const dashboardToken = getDashboardToken();
  if (dashboardToken) {
    try {
      return await run({ Authorization: `Bearer ${dashboardToken}` });
    } catch (e) {
      if (!(e instanceof Error) || !e.message.startsWith("401")) {
        throw e;
      }
    }
  }
  return withSessionToken((token) => run({ Authorization: `Bearer ${token}` }));
}

export const api = {
  getStatus: () => fetchJSON<StatusResponse>("/api/status"),
  getOnboardingStatus: () =>
    fetchJSON<{ needs_onboarding: boolean; has_model: boolean; has_api_key: boolean }>(
      "/api/onboarding/status",
    ),
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
  getTurnStatus: (id: string) =>
    fetchJSON<{
      session_id: string;
      resolved_session_id: string;
      latest_session_id: string;
      active_turn_session_id: string | null;
      turn_active: boolean;
      state?: string;
      reason?: string | null;
      stale_after_seconds?: number;
      idle_for_seconds?: number | null;
      status: string | null;
      phase: "idle" | string;
      started_at: number | null;
      ended_at?: number | null;
      last_event_at: number | null;
      interrupt_requested: boolean;
      active_agent_session_id: string | null;
      stream_revision?: number;
      stream_text_chars?: number;
      timings?: {
        absolute?: Record<string, number>;
        relative_seconds?: Record<string, number>;
      };
      diagnostics?: Record<string, unknown>;
    }>(
      `/api/conversations/${encodeURIComponent(id)}/turn-status`,
    ),
  getConversationDiagnostics: (id: string) =>
    fetchJSON<ConversationDiagnosticsResponse>(
      `/api/conversations/${encodeURIComponent(id)}/diagnostics`,
    ),
  getStreamSnapshot: (id: string, options: { afterChars?: number; tailChars?: number } = {}) => {
    const qs = new URLSearchParams();
    if (typeof options.afterChars === "number") qs.set("after_chars", String(options.afterChars));
    if (typeof options.tailChars === "number") qs.set("tail_chars", String(options.tailChars));
    const query = qs.toString();
    return (
    fetchJSON<{
      session_id: string;
      resolved_session_id: string;
      latest_session_id: string;
      active_turn_session_id: string | null;
      turn_active: boolean;
      state?: string;
      reason?: string | null;
      stale_after_seconds?: number;
      idle_for_seconds?: number | null;
      stream_text: string;
      stream_revision: number;
      stream_text_chars: number;
      stream_text_start?: number;
      stream_text_mode?: "full" | "delta" | "tail" | string;
      stream_text_complete?: boolean;
      timings?: {
        absolute?: Record<string, number>;
        relative_seconds?: Record<string, number>;
      };
      diagnostics?: Record<string, unknown>;
    }>(
      `/api/conversations/${encodeURIComponent(id)}/stream-snapshot${query ? `?${query}` : ""}`,
    )
    );
  },
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
  getLogs: (params: { file?: string; lines?: number; level?: string; component?: string }) => {
    const qs = new URLSearchParams();
    if (params.file) qs.set("file", params.file);
    if (params.lines) qs.set("lines", String(params.lines));
    if (params.level && params.level !== "ALL") qs.set("level", params.level);
    if (params.component && params.component !== "all") qs.set("component", params.component);
    return fetchJSON<LogsResponse>(`/api/logs?${qs.toString()}`);
  },
  getAnalytics: (days: number) =>
    fetchJSON<AnalyticsResponse>(`/api/analytics/usage?days=${days}`),
  getSkillsAnalytics: (limit = 20) =>
    fetchJSON<SkillsAnalyticsResponse>(`/api/analytics/skills?limit=${limit}`),
  getConfig: () => fetchJSON<Record<string, unknown>>("/api/config"),
  getDefaults: () => fetchJSON<Record<string, unknown>>("/api/config/defaults"),
  getSchema: () => fetchJSON<{ fields: Record<string, unknown>; category_order: string[] }>("/api/config/schema"),
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
  getReasoningEffort: () => fetchJSON<ReasoningEffortResponse>("/api/model/reasoning"),
  setReasoningEffort: (effort: string) =>
    fetchJSON<{ effort: string; ok: boolean }>("/api/model/reasoning", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ effort }),
    }),
  saveConfig: (config: Record<string, unknown>) =>
    fetchJSON<{ ok: boolean }>("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config }),
    }),
  getConfigRaw: () => fetchJSON<{ yaml: string }>("/api/config/raw"),
  saveConfigRaw: (yaml_text: string) =>
    fetchJSON<{ ok: boolean }>("/api/config/raw", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml_text }),
    }),
  getEnvVars: () => fetchJSON<Record<string, EnvVarInfo>>("/api/env"),
  setEnvVar: (key: string, value: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    }),
  deleteEnvVar: (key: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }),
  revealEnvVar: (key: string) =>
    withSessionToken((token) =>
      fetchJSON<{ key: string; value: string }>("/api/env/reveal", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ key }),
      }),
    ),

  // Cron jobs
  getCronJobs: () => fetchJSON<CronJob[]>("/api/cron/jobs"),
  createCronJob: (job: { prompt: string; schedule: string; name?: string; deliver?: string }) =>
    fetchJSON<CronJob>("/api/cron/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    }),
  updateCronJob: (id: string, updates: { prompt?: string; schedule?: string; name?: string; deliver?: string }) =>
    fetchJSON<CronJob>(`/api/cron/jobs/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates }),
    }),
  pauseCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/pause`, { method: "POST" }),
  resumeCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/resume`, { method: "POST" }),
  triggerCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/trigger`, { method: "POST" }),
  deleteCronJob: (id: string) =>
    fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}`, { method: "DELETE" }),

  // Skills & Toolsets
  getSkills: () => fetchJSON<SkillInfo[]>("/api/skills"),
  toggleSkill: (name: string, enabled: boolean) =>
    fetchJSON<{ ok: boolean }>("/api/skills/toggle", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, enabled }),
    }),
  getToolsets: () => fetchJSON<ToolsetInfo[]>("/api/tools/toolsets"),

  // Session search (FTS5)
  searchSessions: (q: string, limit = 20, source?: string) => {
    const qs = new URLSearchParams({ q, limit: String(limit) });
    if (source) qs.set("source", source);
    return fetchJSON<SessionSearchResponse>(`/api/sessions/search?${qs.toString()}`);
  },

  // Kanban status management
  patchSessionKanban: (sessionId: string, status: string) =>
    fetchJSON<{ ok: boolean; session_id: string; status: string }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/kanban`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      },
    ),

  // Web chat conversations
  postConversation: (message: string, model?: string, contextItems?: unknown[], source?: string | null) =>
    fetchJSON<{ session_id: string; ok: boolean }>("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, model, context_items: contextItems ?? [], source }),
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
  getConversationSubagents: (sessionId: string) =>
    fetchJSON<ConversationSubagentsResponse>(
      `/api/conversations/${encodeURIComponent(sessionId)}/subagents`,
    ),

  getConversationSubagent: (sessionId: string, subagentId: string) =>
    fetchJSON<ConversationSubagentResponse>(
      `/api/conversations/${encodeURIComponent(sessionId)}/subagents/${encodeURIComponent(subagentId)}`,
    ),

  getConversationSubagentMessages: (sessionId: string, subagentId: string, includeToolResults = false) =>
    fetchJSON<ConversationSubagentMessagesResponse>(
      `/api/conversations/${encodeURIComponent(sessionId)}/subagents/${encodeURIComponent(subagentId)}/messages${includeToolResults ? "?include_tool_results=true" : ""}`,
    ),

  interruptConversationSubagent: (sessionId: string, subagentId: string, message?: string) =>
    fetchJSON<ConversationSubagentInterruptResponse>(
      `/api/conversations/${encodeURIComponent(sessionId)}/subagents/${encodeURIComponent(subagentId)}/interrupt`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message ?? null }),
      },
    ),

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

  getDashboardAuthInfo: () =>
    fetchJSON<DashboardAuthInfo>("/api/dashboard/auth/info"),

  getKanbanBoard: (params: {
    board?: string;
    tenant?: string | null;
    assignee?: string | null;
    archived?: boolean;
    q?: string | null;
  }) => {
    const qs = new URLSearchParams();
    if (params.board) qs.set("board", params.board);
    if (params.tenant) qs.set("tenant", params.tenant);
    if (params.assignee) qs.set("assignee", params.assignee);
    if (params.archived) qs.set("archived", "true");
    if (params.q) qs.set("q", params.q);
    const suffix = qs.toString() ? `?${qs}` : "";
    return fetchJSON<KanbanBoardResponse>(`/api/kanban/board${suffix}`);
  },

  getKanbanTask: (id: string) =>
    fetchJSON<KanbanTaskDetail>(`/api/kanban/tasks/${encodeURIComponent(id)}`),

  createKanbanTask: (body: KanbanTaskCreate) =>
    fetchJSON<KanbanTaskRow>("/api/kanban/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  patchKanbanTask: (id: string, body: KanbanTaskPatch) =>
    fetchJSON<KanbanTaskRow>(`/api/kanban/tasks/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  deleteKanbanTask: (id: string) =>
    fetchJSON<{ ok: boolean; deleted: string }>(`/api/kanban/tasks/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),

  bulkPatchKanbanTasks: (ids: string[], fields: KanbanBulkPatchFields) =>
    fetchJSON<KanbanBulkPatchResponse>("/api/kanban/tasks/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, ...fields }),
    }),

  addKanbanComment: (taskId: string, body: string, author?: string) =>
    fetchJSON<{ ok: boolean; id?: string }>(
      `/api/kanban/tasks/${encodeURIComponent(taskId)}/comments`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body, author: author ?? "web" }),
      },
    ),

  addKanbanLink: (parent_id: string, child_id: string) =>
    fetchJSON<{ ok: boolean }>("/api/kanban/links", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent_id, child_id }),
    }),

  deleteKanbanLink: (parent_id: string, child_id: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/kanban/links?${new URLSearchParams({ parent_id, child_id }).toString()}`,
      { method: "DELETE" },
    ),

  dispatchKanban: (max_tasks = 3, dry_run = false) =>
    fetchJSON<KanbanDispatchResponse>(
      `/api/kanban/dispatch?max_tasks=${max_tasks}&dry_run=${dry_run}`,
      { method: "POST" },
    ),

  completeKanbanTask: (id: string, summary: string, result = "") =>
    fetchJSON<KanbanTaskRow>(`/api/kanban/tasks/${encodeURIComponent(id)}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ summary, result, metadata: {} }),
    }),

  blockKanbanTask: (id: string, reason: string) =>
    fetchJSON<KanbanTaskRow>(`/api/kanban/tasks/${encodeURIComponent(id)}/block`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }),

  unblockKanbanTask: (id: string) =>
    fetchJSON<KanbanTaskRow>(`/api/kanban/tasks/${encodeURIComponent(id)}/unblock`, {
      method: "POST",
    }),

  // Admin surfaces
  getAdminActions: () => fetchJSON<AdminActionsResponse>("/api/admin/actions"),
  runAdminAction: (id: string, args: Record<string, unknown> = {}, confirm = false) =>
    fetchJSON<AdminRunStartResponse>(`/api/admin/actions/${encodeURIComponent(id)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ args, confirm }),
    }),
  getAdminRun: (runId: string) =>
    fetchJSON<AdminRun>(`/api/admin/actions/runs/${encodeURIComponent(runId)}`),
  getGatewayAdminStatus: () => fetchJSON<GatewayAdminStatus>("/api/gateway/status"),
  controlGateway: (action: string, confirm = false) =>
    fetchJSON<AdminRunStartResponse>("/api/gateway/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, confirm }),
    }),
  getProfiles: () => fetchJSON<ProfilesResponse>("/api/profiles"),
  createProfile: (body: ProfileCreateRequest) =>
    fetchJSON<{ ok: boolean; path: string; profiles: ProfileInfo[] }>("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  useProfile: (name: string) =>
    fetchJSON<{ ok: boolean; active: string }>(`/api/profiles/${encodeURIComponent(name)}/use`, {
      method: "POST",
    }),
  deleteProfile: (name: string, confirm = false) =>
    fetchJSON<{ ok: boolean }>(`/api/profiles/${encodeURIComponent(name)}?confirm=${confirm}`, {
      method: "DELETE",
    }),
  exportProfile: (name: string, output_path?: string, confirm = false) =>
    fetchJSON<{ ok: boolean; path: string }>(`/api/profiles/${encodeURIComponent(name)}/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ output_path, confirm }),
    }),
  importProfile: (archive_path: string, name?: string, confirm = false) =>
    fetchJSON<{ ok: boolean; path: string }>("/api/profiles/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ archive_path, name, confirm }),
    }),
  getPlugins: () => fetchJSON<PluginsResponse>("/api/plugins"),
  runPluginAction: (action: string, name: string, confirm = false) =>
    fetchJSON<AdminRunStartResponse>(`/api/plugins/${encodeURIComponent(action)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, confirm }),
    }),
  getMcpServers: () => fetchJSON<McpServersResponse>("/api/mcp/servers"),
  addMcpServer: (body: McpServerCreate) =>
    fetchJSON<{ ok: boolean; name: string; server: Record<string, unknown> }>("/api/mcp/servers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteMcpServer: (name: string, confirm = false) =>
    fetchJSON<{ ok: boolean }>(`/api/mcp/servers/${encodeURIComponent(name)}?confirm=${confirm}`, {
      method: "DELETE",
    }),
  testMcpServer: (name: string) =>
    fetchJSON<AdminRunStartResponse>(`/api/mcp/servers/${encodeURIComponent(name)}/test`, {
      method: "POST",
    }),
  getDiagnosticsSummary: () => fetchJSON<DiagnosticsSummary>("/api/diagnostics/summary"),
  checkForUpdate: () => fetchJSON<{ update_available: boolean; commits_behind: number | null }>("/api/update/check"),
  checkMacUpdate: () =>
    fetchJSON<{
      update_available: boolean;
      latest_version: string | null;
      current_version: string | null;
      download_url: string | null;
      release_url: string | null;
      release_notes?: string | null;
      release_name?: string | null;
      published_at?: string | null;
    }>("/api/mac/update/check"),
  runMacUpdate: () =>
    fetchJSON<{
      ok: boolean;
      path: string;
      installer_script: string;
      log_path: string;
      latest_version: string | null;
      status: "installing";
    }>("/api/mac/update/run", {
      method: "POST",
    }),
  setupOnboardingSkills: (mode: "recommended" | "minimal" | "none") =>
    fetchJSON<{ ok: boolean; mode: string; seeded: number; total_bundled: number }>(
      "/api/onboarding/skills",
      { method: "POST", body: JSON.stringify({ mode }), headers: { "Content-Type": "application/json" } },
    ),

  getCodexUsage: () =>
    fetchJSON<{ available: boolean; reason?: string; data?: Record<string, unknown> }>("/api/model/codex-usage"),

  // OAuth provider management
  getOAuthProviders: () =>
    fetchJSON<OAuthProvidersResponse>("/api/providers/oauth"),
  disconnectOAuthProvider: (providerId: string) =>
    withDashboardOrSessionToken((authHeader) =>
      fetchJSON<{ ok: boolean; provider: string }>(
        `/api/providers/oauth/${encodeURIComponent(providerId)}`,
        {
          method: "DELETE",
          headers: authHeader,
        },
      ),
    ),
  startOAuthLogin: (providerId: string) =>
    withDashboardOrSessionToken((authHeader) =>
      fetchJSON<OAuthStartResponse>(
        `/api/providers/oauth/${encodeURIComponent(providerId)}/start`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeader,
          },
          body: "{}",
        },
      ),
    ),
  submitOAuthCode: (providerId: string, sessionId: string, code: string) =>
    withDashboardOrSessionToken((authHeader) =>
      fetchJSON<OAuthSubmitResponse>(
        `/api/providers/oauth/${encodeURIComponent(providerId)}/submit`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...authHeader,
          },
          body: JSON.stringify({ session_id: sessionId, code }),
        },
      ),
    ),
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
  openExternalUrl: (url: string) =>
    fetchJSON<{ opened: boolean }>(`/api/system/open-external`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),

  // Slash commands list (gateway-available only)
  getCommands: () => fetchJSON<SlashCommand[]>("/api/commands"),

  // Workspace
  listWorkspaceProjects: () =>
    fetchJSON<WorkspaceProjectsResponse>("/api/workspace/projects"),

  listProjectTemplates: () =>
    fetchJSON<ProjectTemplatesResponse>("/api/workspace/project-templates"),

  createWorkspaceProject: (request: ProjectCreateRequest | string, template = "scratch") => {
    const body = typeof request === "string" ? { name: request, template } : request;
    return fetchJSON<{ ok: boolean; slug: string; name: string; path: string; template: string }>(
      "/api/workspace/projects",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
  },

  deleteWorkspaceProject: (slug: string) =>
    fetchJSON<{ ok: boolean; deleted: string }>(`/api/workspace/projects/${encodeURIComponent(slug)}`, {
      method: "DELETE",
    }),

  renameWorkspaceProject: (slug: string, name: string) =>
    fetchJSON<{
      ok: boolean;
      old_slug: string;
      slug: string;
      name: string;
      path: string;
      mtime: number;
      migrated_sessions: number;
    }>(`/api/workspace/projects/${encodeURIComponent(slug)}/rename-project`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  getWorkspaceFileTree: (slug: string, showHidden = false) =>
    fetchJSON<WorkspaceTreeResponse>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/tree${showHidden ? "?show_hidden=true" : ""}`,
    ),

  getWorkspaceFile: (slug: string, path: string) => {
    const qs = new URLSearchParams({ path });
    return fetchJSON<WorkspaceFileContent>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/file?${qs}`,
    );
  },

  uploadWorkspaceFiles: async (slug: string, files: File[], path = "") => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    const qs = path ? `?path=${encodeURIComponent(path)}` : "";
    const res = await fetch(
      `/api/workspace/projects/${encodeURIComponent(slug)}/upload${qs}`,
      { method: "POST", headers: authHeaders(), body: form },
    );
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status}: ${text}`);
    }
    return res.json() as Promise<{ ok: boolean; saved: Array<{ filename: string; size: number }> }>;
  },

  uploadChatFiles: async (files: File[]) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    const res = await fetch("/api/workspace/files/upload", {
      method: "POST",
      headers: authHeaders(),
      body: form,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => res.statusText);
      throw new Error(`${res.status}: ${text}`);
    }
    return res.json() as Promise<{
      ok: boolean;
      saved: Array<{ filename: string; path: string; absolute_path: string; size: number }>;
    }>;
  },

  listWorkspaceDir: (slug: string, path = "", showHidden = false) => {
    const qs = new URLSearchParams();
    if (path) qs.set("path", path);
    if (showHidden) qs.set("show_hidden", "true");
    const query = qs.toString();
    return fetchJSON<FileListResponse>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/list${query ? `?${query}` : ""}`,
    );
  },

  listChatFiles: (path = "", showHidden = false) => {
    const qs = new URLSearchParams();
    if (path) qs.set("path", path);
    if (showHidden) qs.set("show_hidden", "true");
    const query = qs.toString();
    return fetchJSON<FileListResponse>(
      `/api/workspace/files/list${query ? `?${query}` : ""}`,
    );
  },

  deleteChatFile: (path: string) => {
    const qs = new URLSearchParams({ path });
    return fetchJSON<{ ok: boolean; deleted: string }>(
      `/api/workspace/files?${qs}`,
      { method: "DELETE" },
    );
  },

  readChatFile: async (path: string): Promise<string> => {
    const url = mediaFileUrl(path);
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`);
    return res.text();
  },

  writeChatFile: async (path: string, content: string): Promise<void> => {
    const qs = new URLSearchParams({ path });
    await fetchJSON<{ ok: boolean }>(`/api/workspace/files?${qs}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
  },

  deleteWorkspaceFile: (slug: string, path: string) => {
    const qs = new URLSearchParams({ path });
    return fetchJSON<{ ok: boolean; deleted: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/file?${qs}`,
      { method: "DELETE" },
    );
  },

  writeWorkspaceFile: (slug: string, path: string, content: string) => {
    const qs = new URLSearchParams({ path });
    return fetchJSON<{ ok: boolean; path: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/file?${qs}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      },
    );
  },

  makeWorkspaceDir: (slug: string, path: string) => {
    const qs = new URLSearchParams({ path });
    return fetchJSON<{ ok: boolean; path: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/mkdir?${qs}`,
      { method: "POST" },
    );
  },

  renameWorkspacePath: (slug: string, src: string, dst: string) =>
    fetchJSON<{ ok: boolean; src: string; dst: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/rename`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ src, dst }),
      },
    ),

  getWorkspaceGitStatus: (slug: string) =>
    fetchJSON<WorkspaceGitStatus>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/git/status`,
    ),

  getWorkspaceGitDiff: (slug: string, path = "") => {
    const qs = path ? `?${new URLSearchParams({ path })}` : "";
    return fetchJSON<{ path: string | null; diff: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/git/diff${qs}`,
    );
  },

  revertWorkspaceGitFile: (slug: string, path: string) =>
    fetchJSON<{ ok: boolean; reverted: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/git/revert`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      },
    ),

  runWorkspaceTerminalCommand: (slug: string, command?: string) =>
    fetchJSON<WorkspaceTerminalRunStart>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/terminal/runs`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: command ? JSON.stringify({ command }) : "{}",
      },
    ),

  streamWorkspaceTerminalRun: (slug: string, runId: string): EventSource =>
    new EventSource(
      sseUrl(
        `/api/workspace/projects/${encodeURIComponent(slug)}/terminal/runs/${encodeURIComponent(runId)}/stream`,
      ),
    ),

  stopWorkspaceTerminalRun: (slug: string, runId: string) =>
    fetchJSON<{ ok: boolean; run_id: string; status: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/terminal/runs/${encodeURIComponent(runId)}/stop`,
      { method: "POST" },
    ),

  sendWorkspaceTerminalInput: (slug: string, runId: string, input: string) =>
    fetchJSON<{ ok: boolean; run_id: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/terminal/runs/${encodeURIComponent(runId)}/input`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input }),
      },
    ),

  resizeWorkspaceTerminal: (slug: string, runId: string, rows: number, cols: number) =>
    fetchJSON<{ ok: boolean; run_id: string; rows: number; cols: number }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/terminal/runs/${encodeURIComponent(runId)}/resize`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows, cols }),
      },
    ),

  getWorkspacePreviewStatus: (slug: string) =>
    fetchJSON<WorkspacePreviewStatus>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/status`,
    ),

  startWorkspacePreview: (slug: string, options?: { command?: string; url?: string; port?: number }) =>
    fetchJSON<WorkspacePreviewStatus>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/start`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(options ?? {}),
      },
    ),

  stopWorkspacePreview: (slug: string) =>
    fetchJSON<WorkspacePreviewStatus>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stop`,
      { method: "POST" },
    ),

  restartWorkspacePreview: (slug: string, options?: { command?: string; url?: string; port?: number }) =>
    fetchJSON<WorkspacePreviewStatus>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/restart`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(options ?? {}),
      },
    ),

  navigateWorkspacePreview: (slug: string, url: string) =>
    fetchJSON<WorkspacePreviewStatus>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/navigate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      },
    ),

  // ── Canvas interaction ──
  canvasInteract: (body: { scope: string; slug: string | null; canvas_id: string; widget_id: string; value: string }) =>
    fetchJSON<{ ok: boolean }>(`/api/canvases/interact`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // ── Memory ──
  getMemory: () => fetchJSON<MemoryListResponse>(`/api/memory`),
  addMemoryEntry: (target: string, content: string) =>
    fetchJSON<MemoryTargetPayload>(`/api/memory/${encodeURIComponent(target)}/entry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  replaceMemoryEntry: (target: string, oldText: string, newContent: string) =>
    fetchJSON<MemoryTargetPayload>(`/api/memory/${encodeURIComponent(target)}/replace`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_text: oldText, new_content: newContent }),
    }),
  removeMemoryEntry: (target: string, oldText: string) =>
    fetchJSON<MemoryTargetPayload>(`/api/memory/${encodeURIComponent(target)}/entry`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_text: oldText }),
    }),

  refreshWorkspacePreview: (slug: string) =>
    fetchJSON<{ ok: boolean; slug: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/refresh`,
      { method: "POST" },
    ),

  // ── Streamed server-side browser (WebUI path) ──
  streamBrowserNavigate: (slug: string, url: string, persistent = true) =>
    fetchJSON<{ slug: string; url: string; title: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/navigate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, persistent }),
      },
    ),

  /** Relative URL for the latest frame; pass a cache-buster to force a refetch. */
  streamBrowserFrameUrl: (slug: string, bust: number) =>
    `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/frame?t=${bust}`,

  /** SSE endpoint that pushes CDP-screencast JPEG frames (base64). 501 → poll. */
  streamBrowserScreencastUrl: (slug: string) =>
    `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/screencast`,

  streamBrowserInput: (slug: string, input: StreamBrowserInput) =>
    fetchJSON<{ slug: string; ok: boolean; url: string; title: string; clipboard?: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/input`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      },
    ),

  streamBrowserBackend: (slug: string) =>
    fetchJSON<{ slug: string; backend: string; available: boolean; detail: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/backend`,
    ),

  /** Resize the streamed viewport (responsive presets). */
  streamBrowserViewport: (slug: string, width: number, height: number) =>
    fetchJSON<{ slug: string; width: number; height: number }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/viewport`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ width, height }),
      },
    ),

  /** Toggle dark-mode (prefers-color-scheme) emulation; dark=null clears. */
  streamBrowserEmulate: (slug: string, dark: boolean | null) =>
    fetchJSON<{ slug: string; dark: boolean | null }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/emulate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dark }),
      },
    ),

  streamBrowserTabs: (slug: string) =>
    fetchJSON<{ slug: string; tabs: StreamBrowserTab[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/tabs`,
    ),

  streamBrowserTabAction: (
    slug: string,
    action: "new" | "switch" | "close",
    opts?: { url?: string; target_id?: string },
  ) =>
    fetchJSON<{ slug: string; ok: boolean; url?: string; title?: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/tabs`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ...opts }),
      },
    ),

  streamBrowserDownloads: (slug: string) =>
    fetchJSON<{ slug: string; downloads: StreamBrowserDownload[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/downloads`,
    ),

  /** Whether the user currently holds control (take-over) of the session. */
  streamBrowserTakeoverState: (slug: string) =>
    fetchJSON<{ slug: string; paused: boolean; ts: number }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/takeover`,
    ),

  /** Grab (true) or release (false) control of the shared session. */
  streamBrowserTakeover: (slug: string, paused: boolean) =>
    fetchJSON<{ slug: string; paused: boolean }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/takeover`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paused }),
      },
    ),

  /** Element picker: describe the element at a pane coordinate. */
  streamBrowserPick: (slug: string, x: number, y: number) =>
    fetchJSON<{ slug: string; element: StreamBrowserPickedElement }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/pick`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y }),
      },
    ),

  /** Capture the current frame as PNG (saved to workspace) for send-to-chat. */
  streamBrowserScreenshot: (slug: string) =>
    fetchJSON<{ slug: string; url: string; png_base64: string; name: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/screenshot`,
    ),

  /** Record a short flow as an animated GIF saved to the workspace. */
  streamBrowserRecord: (slug: string, frames = 12, interval = 0.4) =>
    fetchJSON<{ slug: string; name: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/record`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ frames, interval }),
      },
    ),

  /** Captured console/network/exception entries from the previewed page. */
  streamBrowserConsole: (slug: string, sinceSeq = 0) =>
    fetchJSON<{ slug: string; entries: StreamBrowserConsoleEntry[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/console?since_seq=${sinceSeq}`,
    ),

  /** Auto-detected local dev servers owned by this workspace. */
  detectDevServers: (slug: string) =>
    fetchJSON<{ slug: string; servers: { url: string; port: number }[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/detect-servers`,
    ),

  installStreamBrowser: (slug: string) =>
    fetchJSON<{ slug: string; ok: boolean; error?: string | null; version?: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/install`,
      { method: "POST" },
    ),

  stopStreamBrowser: (slug: string) =>
    fetchJSON<{ slug: string; stopped: boolean }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/stop`,
      { method: "POST" },
    ),

  streamBrowserCookies: (slug: string) =>
    fetchJSON<{ slug: string; cookies: { name: string; domain: string }[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/cookies`,
    ),

  clearStreamBrowser: (slug: string) =>
    fetchJSON<{ slug: string; cleared: boolean }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/clear`,
      { method: "POST" },
    ),

  getWorkspacePreviewLogs: (slug: string) =>
    fetchJSON<{ slug: string; logs: WorkspacePreviewLog[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/logs`,
    ),

  /** Auditable agent browser action transcript (navigate/click/type/a11y…). */
  getWorkspacePreviewActionLog: (slug: string, sinceTs?: number, limit = 500) =>
    fetchJSON<{ slug: string; actions: BrowserActionLogEntry[]; count: number }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/action-log?limit=${limit}` +
        (sinceTs ? `&since_ts=${sinceTs}` : ""),
    ),

  getWorkspacePreviewSnapshot: (slug: string) =>
    fetchJSON<WorkspacePreviewSnapshot>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/snapshot`,
    ),

  getWorkspacePreviewConsole: (slug: string) =>
    fetchJSON<{ slug: string; messages: WorkspacePreviewLog[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/console`,
    ),

  workspacePreviewClick: (slug: string, selector: string) =>
    fetchJSON<{ slug: string; action: string; result: unknown; messages: WorkspacePreviewLog[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/click`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selector }),
      },
    ),

  workspacePreviewType: (slug: string, selector: string, text: string) =>
    fetchJSON<{ slug: string; action: string; result: unknown; messages: WorkspacePreviewLog[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/type`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ selector, text }),
      },
    ),

  workspacePreviewEvaluate: (slug: string, expression: string) =>
    fetchJSON<{ slug: string; action: string; result: unknown; messages: WorkspacePreviewLog[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/evaluate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expression }),
      },
    ),

  streamWorkspacePreviewEvents: (slug: string): EventSource =>
    new EventSource(
      sseUrl(`/api/workspace/projects/${encodeURIComponent(slug)}/preview/events`),
    ),

  startWorkspaceConversation: (slug: string, message: string, model?: string, contextItems?: unknown[]) =>
    fetchJSON<{ session_id: string; ok: boolean; source: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/conversations`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, model, context_items: contextItems ?? [] }),
      },
    ),

  listWorkspaceConversations: (slug: string, limit = 30, offset = 0) => {
    const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    return fetchJSON<PaginatedSessions>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/conversations?${qs}`,
    );
  },

  // Artifacts
  listArtifacts: (type: string = "all", limit = 200) =>
    fetchJSON<ArtifactsResponse>(
      `/api/artifacts?type=${encodeURIComponent(type)}&limit=${limit}`,
    ),

  // Messaging platforms
  listMessagingPlatforms: () =>
    fetchJSON<MessagingPlatformsResponse>("/api/messaging/platforms"),

  updateMessagingPlatform: (
    platformId: string,
    body: { enabled?: boolean; values?: Record<string, string | boolean> },
  ) =>
    fetchJSON<MessagingPlatform>(
      `/api/messaging/platforms/${encodeURIComponent(platformId)}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    ),

  // Connectors
  listConnectors: () =>
    fetchJSON<ConnectorStatus[]>("/api/connectors"),

  getGoogleStatus: () =>
    fetchJSON<ConnectorStatus>("/api/connectors/google/status"),

  getConnectorStatus: (connectorId: string) =>
    fetchJSON<ConnectorStatus>(`/api/connectors/${encodeURIComponent(connectorId)}/status`),

  getGoogleSetup: () =>
    fetchJSON<GoogleSetupInfo>("/api/connectors/google/setup"),

  connectGoogle: () =>
    fetchJSON<{ auth_url?: string; error?: string; message?: string }>(
      "/api/connectors/google/connect",
      { method: "POST" },
    ),

  connectConnector: (connectorId: string) =>
    fetchJSON<{
      auth_url?: string;
      flow?: "device_code" | "oauth" | "mcp" | "mcp_oauth";
      device_state?: string;
      user_code?: string;
      verification_uri?: string;
      expires_in?: number;
      interval?: number;
      connected?: boolean;
      state?: string;
      detail?: string;
      connect_state?: string;
      poll_url?: string;
      error?: string;
      message?: string;
    }>(
      `/api/connectors/${encodeURIComponent(connectorId)}/connect`,
      { method: "POST" },
    ),

  getConnectorConnectStatus: (connectorId: string) =>
    fetchJSON<{
      connected?: boolean;
      state?: string;
      detail?: string;
      connect_state?: string;
      connect_error?: string;
      error?: string;
    }>(`/api/connectors/${encodeURIComponent(connectorId)}/connect/status`),

  saveConnectorApiKey: (connectorId: string, apiKey: string, envVar = "") =>
    fetchJSON<
      ConnectorStatus & {
        saved?: boolean;
        env_var?: string;
        error?: string;
        message?: string;
      }
    >(`/api/connectors/${encodeURIComponent(connectorId)}/api-key`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKey, env_var: envVar }),
    }),

  pollConnectorDevice: (connectorId: string, device_state: string) =>
    fetchJSON<{
      connected?: boolean;
      pending?: boolean;
      account?: string | null;
      interval?: number;
      error?: string;
    }>(`/api/connectors/${encodeURIComponent(connectorId)}/device/poll`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_state }),
    }),

  connectGoogleGmailImap: (email: string, app_password: string) =>
    fetchJSON<{ connected?: boolean; email?: string; error?: string }>(
      "/api/connectors/google/gmail-imap",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, app_password }),
      },
    ),

  disconnectGoogleGmailImap: () =>
    fetchJSON<{ disconnected?: boolean; error?: string }>(
      "/api/connectors/google/gmail-imap",
      { method: "DELETE" },
    ),

  disconnectGoogle: () =>
    fetchJSON<{ disconnected?: boolean; skills_disabled?: string[]; error?: string }>(
      "/api/connectors/google",
      { method: "DELETE" },
    ),

  disconnectConnector: (connectorId: string, disableSkills = true) =>
    fetchJSON<{
      disconnected?: boolean;
      env_cleared?: string[];
      skills_disabled?: string[];
      error?: string;
    }>(
      `/api/connectors/${encodeURIComponent(connectorId)}?disable_skills=${disableSkills}`,
      { method: "DELETE" },
    ),

  enableConnectorSkills: (connectorId: string) =>
    fetchJSON<{ ok?: boolean; skills?: string[]; toolsets?: string[]; error?: string }>(
      `/api/connectors/${encodeURIComponent(connectorId)}/skills/enable`,
      { method: "POST" },
    ),

  getConnectorCliTools: () =>
    fetchJSON<CliToolInfo[]>("/api/connectors/cli-tools"),

  // ── Workflows (Canvas execution engine) ──
  getWorkflowNodeTypes: () =>
    fetchJSON<{ nodeTypes: WorkflowNodeType[] }>("/api/workflows/node-types"),

  runWorkflow: (doc: CanvasDoc, trigger = "manual") =>
    fetchJSON<WorkflowRunResult>("/api/workflows/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc, trigger }),
    }),

  runWorkflowAsync: (doc: CanvasDoc, trigger = "manual") =>
    fetchJSON<{ executionId: string; status: string }>("/api/workflows/run-async", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc, trigger }),
    }),

  streamWorkflowRun: (executionId: string): EventSource =>
    new EventSource(sseUrl(`/api/workflows/runs/${encodeURIComponent(executionId)}/events`)),

  cancelWorkflowRun: (executionId: string) =>
    fetchJSON<{ ok: boolean; executionId: string; status: string }>(
      `/api/workflows/runs/${encodeURIComponent(executionId)}/cancel`,
      { method: "POST" },
    ),

  runWorkflowNode: (doc: CanvasDoc, nodeId: string, seed?: WorkflowItem[]) =>
    fetchJSON<WorkflowRunResult>("/api/workflows/run-node", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc, nodeId, seed }),
    }),

  listWorkflowExecutions: (canvas?: string, scope?: string, slug?: string | null) => {
    const qs = new URLSearchParams();
    if (canvas) qs.set("canvas", canvas);
    if (scope) qs.set("scope", scope);
    if (slug) qs.set("slug", slug);
    return fetchJSON<{ executions: WorkflowExecutionSummary[] }>(
      `/api/workflows/executions${qs.toString() ? `?${qs}` : ""}`,
    );
  },

  getWorkflowExecution: (executionId: string) =>
    fetchJSON<WorkflowExecutionDetail>(`/api/workflows/executions/${encodeURIComponent(executionId)}`),

  registerWorkflowTriggers: (doc: CanvasDoc) =>
    fetchJSON<{ ok: boolean; triggers: WorkflowTrigger[] }>("/api/workflows/triggers/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc }),
    }),

  // ── Canvas ──
  listCanvases: () => fetchJSON<CanvasListResponse>("/api/canvases"),

  // Stateless, canvas-local agent turn (does NOT create a Chat-tab session).
  postCanvasChat: (
    message: string,
    history: Array<{ role: string; content: string }> = [],
    opts: { model?: string; slug?: string | null } = {},
  ) =>
    fetchJSON<{ ok: boolean; reply: string; model: string }>("/api/canvas/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history, model: opts.model, slug: opts.slug ?? null }),
    }),

  getCanvas: (scope: CanvasScope, id: string, slug?: string | null) =>
    fetchJSON<CanvasDoc>(canvasUrl(scope, id, slug)),

  saveCanvas: (doc: CanvasDoc) =>
    fetchJSON<{ ok: boolean; id: string; scope: CanvasScope; slug: string | null; updatedAt: string; revision: string }>(
      canvasUrl(doc.scope, doc.id, doc.slug),
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(doc),
      },
    ),

  deleteCanvas: (scope: CanvasScope, id: string, slug?: string | null) =>
    fetchJSON<{ ok: boolean; deleted: string }>(canvasUrl(scope, id, slug), {
      method: "DELETE",
    }),
};

function canvasUrl(scope: CanvasScope, id: string, slug?: string | null): string {
  const encId = encodeURIComponent(id);
  if (scope === "project") {
    if (!slug) throw new Error("Project canvas requires a slug");
    return `/api/canvases/project/${encodeURIComponent(slug)}/${encId}`;
  }
  return `/api/canvases/global/${encId}`;
}

/**
 * Open an external URL reliably across desktop and browser.
 *
 * In the Tauri desktop app the webview can't open new windows/tabs, so we ask
 * the local backend to open it via the OS. In a plain browser the backend
 * reports `opened: false` and we fall back to window.open.
 */
export async function openExternal(url: string): Promise<void> {
  try {
    const res = await api.openExternalUrl(url);
    if (res.opened) return;
  } catch {
    // fall through to window.open
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

export interface PlatformStatus {
  error_code?: string;
  error_message?: string;
  state: string;
  updated_at: string;
}

export interface StatusResponse {
  active_sessions: number;
  config_path: string;
  config_version: number;
  env_path: string;
  gateway_exit_reason: string | null;
  gateway_pid: number | null;
  gateway_platforms: Record<string, PlatformStatus>;
  gateway_running: boolean;
  gateway_state: string | null;
  gateway_updated_at: string | null;
  spark_home: string;
  latest_config_version: number;
  release_date: string;
  server_instance_id?: string;
  version: string;
  update_available?: boolean;
  commits_behind?: number | null;
  desktop?: boolean;
  desktop_version?: string | null;
  desktop_platform?: "macos" | "windows" | "linux" | null;
  mac_update_available?: boolean;
  mac_latest_version?: string | null;
  dashboard_auth?: {
    token_file: string;
    require_auth_nonlocal: boolean;
  };
  dashboard_features?: {
    subagents_sidebar?: boolean;
  };
  streaming_health?: {
    checkpoint_writes: number;
    checkpoint_write_errors: number;
    checkpoint_write_seconds_avg: number;
    checkpoint_write_seconds_max: number;
    turn_lock_wait_seconds_avg: number;
    turn_lock_wait_seconds_max: number;
    turn_lock_wait_samples: number;
    event_drops: number;
    event_drop_keys: number;
    loop_lag_seconds: number;
    loop_lag_seconds_max: number;
    executor_submitted: number;
    executor_completed: number;
    executor_running: number;
    executor_queued: number;
    executor_queue_wait_seconds_avg: number;
    executor_queue_wait_seconds_max: number;
    agent_cache_size: number;
    agent_cache_evictions: number;
    warm_session_deduped: number;
    fanout_latency_seconds_avg: number;
    fanout_latency_seconds_max: number;
    fanout_latency_samples: number;
  };
}

export interface DashboardAuthInfo {
  require_auth_nonlocal: boolean;
  token_file: string;
  hint: string;
}

export interface KanbanTaskRow {
  id: string;
  title: string;
  body?: string | null;
  status: string;
  assignee?: string | null;
  tenant?: string | null;
  priority?: number;
  in_triage?: number;
  board_slug?: string;
  workspace_path?: string | null;
  updated_at?: number;
  result?: string | null;
  [key: string]: unknown;
}

export interface KanbanTaskCreate {
  title: string;
  body?: string;
  board?: string;
  assignee?: string | null;
  tenant?: string | null;
  priority?: number;
  parents?: string[];
  idempotency_key?: string | null;
  workspace_kind?: string;
  workspace_path?: string | null;
  skills?: string[];
  owner_profile?: string | null;
  owner_platform?: string | null;
  owner_channel?: string | null;
  owner_thread_id?: string | null;
  creator_session_key?: string | null;
  creator_session_source?: Record<string, unknown>;
  notify_on_changes?: boolean;
  wake_on_changes?: boolean;
  triage?: boolean;
  max_runtime_seconds?: number;
}

export interface KanbanTaskPatch {
  status?: string | null;
  title?: string | null;
  body?: string | null;
  assignee?: string | null;
  priority?: number | null;
  tenant?: string | null;
  result?: string | null;
  in_triage?: boolean | null;
  workspace_path?: string | null;
  actor?: string | null;
  origin_session_key?: string | null;
  origin_kind?: string | null;
  internal_event?: boolean;
}

export interface KanbanBulkPatchFields {
  status?: string | null;
  assignee?: string | null;
  priority?: number | null;
}

export interface KanbanBulkPatchResponse {
  ok: boolean;
  errors: Record<string, string>;
}

export interface KanbanDispatchResponse {
  ok?: boolean;
  claimed?: number;
  task_ids?: string[];
  dry_run?: boolean;
  ready?: string[];
  blocked_by_assignee?: string[];
}

export interface KanbanBoardResponse {
  board_slug: string;
  columns: Record<string, KanbanTaskRow[]>;
  assignees: string[];
  tenants: string[];
  boards: Array<Record<string, unknown>>;
}

export interface KanbanTaskDetail extends KanbanTaskRow {
  parents: string[];
  children: string[];
  comments: Array<{ id: number; author?: string | null; body: string; created_at: number }>;
  events: Array<{
    id: number;
    kind: string;
    payload_json?: string | null;
    created_at: number;
    run_id?: number | null;
  }>;
  runs: Array<{
    id: number;
    outcome: string;
    profile?: string | null;
    started_at: number;
    ended_at?: number | null;
    summary?: string | null;
    error?: string | null;
  }>;
  worker_context?: string;
}

export interface SessionInfo {
  id: string;
  source: string | null;
  model: string | null;
  title: string | null;
  started_at: number;
  ended_at: number | null;
  last_active: number;
  is_active: boolean;
  message_count: number;
  tool_call_count: number;
  input_tokens: number;
  output_tokens: number;
  preview: string | null;
  kanban_status: string | null;
  estimated_cost_usd: number | null;
}

export interface PaginatedSessions {
  sessions: SessionInfo[];
  total: number;
  limit: number;
  offset: number;
}

export interface EnvVarInfo {
  is_set: boolean;
  redacted_value: string | null;
  description: string;
  url: string | null;
  category: string;
  is_password: boolean;
  tools: string[];
  advanced: boolean;
}

export interface SessionMessage {
  id?: string;
  message_index?: number;
  role: "user" | "assistant" | "system" | "tool";
  content: string | null;
  result_preview?: string | null;
  result_chars?: number | null;
  result_truncated?: boolean | null;
  has_full_result?: boolean | null;
  tool_calls?: Array<{
    id: string;
    function: { name: string; arguments: string };
  }>;
  tool_name?: string;
  tool_call_id?: string;
  timestamp?: number;
  reasoning?: string | null;
}

export interface SessionMessagesResponse {
  session_id: string;
  messages: SessionMessage[];
  total?: number;
  has_earlier?: boolean;
  page_start_index?: number | null;
  page_end_index?: number | null;
  next_before_id?: string | number | null;
  /**
   * Set when the requested session was a parent of a compression-driven
   * lineage; identifies the originally-requested ID. The returned messages
   * come from the leaf (`session_id`) so the agent's current state is shown.
   */
  migrated_from?: string;
}

export interface LogsResponse {
  file: string;
  lines: string[];
}

export interface AnalyticsDailyEntry {
  day: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  reasoning_tokens: number;
  estimated_cost: number;
  actual_cost: number;
  sessions: number;
}

export interface AnalyticsModelEntry {
  model: string;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  sessions: number;
}

export interface AnalyticsResponse {
  daily: AnalyticsDailyEntry[];
  by_model: AnalyticsModelEntry[];
  totals: {
    total_input: number;
    total_output: number;
    total_cache_read: number;
    total_reasoning: number;
    total_estimated_cost: number;
    total_actual_cost: number;
    total_sessions: number;
  };
}

export interface CronJob {
  id: string;
  name?: string;
  prompt: string;
  schedule: { kind: string; expr: string; display: string };
  schedule_display: string;
  enabled: boolean;
  state: string;
  deliver?: string;
  last_run_at?: string | null;
  next_run_at?: string | null;
  last_error?: string | null;
}

export interface SkillInfo {
  name: string;
  description: string;
  category: string;
  enabled: boolean;
  use_count: number;
  view_count: number;
  patch_count: number;
  skill_state: string;
}

export interface SkillUsageEntry {
  name: string;
  state: string;
  created_by: string | null;
  activity_count: number;
  use_count: number;
  view_count: number;
  patch_count: number;
  last_activity_at: string | null;
}

export interface SkillLifecycleCounts {
  active: number;
  stale: number;
  archived: number;
}

export interface SkillsAnalyticsResponse {
  top_skills: SkillUsageEntry[];
  lifecycle_counts: SkillLifecycleCounts;
}

export interface ToolsetInfo {
  name: string;
  label: string;
  description: string;
  enabled: boolean;
  configured: boolean;
  tools: string[];
}

export interface SessionSearchResult {
  session_id: string;
  snippet: string;
  role: string | null;
  source: string | null;
  model: string | null;
  title: string | null;
  session_started: number | null;
}

export interface SessionSearchResponse {
  results: SessionSearchResult[];
}

export interface ConversationModelEntry {
  id: string;
  hint: string;
}

export interface ConversationModelsResponse {
  models: ConversationModelEntry[];
}

export interface AdminActionMeta {
  id: string;
  label: string;
  description: string;
  risk: "low" | "medium" | "high" | string;
  requires_confirmation: boolean;
  long_running: boolean;
  args_schema: Record<string, unknown>;
  available: boolean;
  unavailable_reason?: string | null;
}

export interface AdminActionsResponse {
  ok: boolean;
  actions: AdminActionMeta[];
}

export interface AdminRunStartResponse {
  run_id: string;
  status: "queued" | "running" | "done" | "failed";
}

export interface AdminRunOutputLine {
  stream: string;
  text: string;
  ts: number;
}

export interface AdminRun {
  run_id: string;
  action_id: string;
  args: Record<string, unknown>;
  status: "queued" | "running" | "done" | "failed";
  started_at?: number | null;
  finished_at?: number | null;
  exit_code?: number | null;
  output_tail: AdminRunOutputLine[];
  error?: string | null;
}

export interface GatewayAdminStatus {
  ok: boolean;
  running: boolean;
  pid: number | null;
  runtime: Record<string, unknown>;
  platforms: Record<string, unknown>;
  configured_platforms: Array<{ id: string; configured: boolean }>;
  service_system: string;
  last_error?: string | null;
  state?: string | null;
}

export interface ProfileInfo {
  name: string;
  path: string;
  is_default: boolean;
  is_active: boolean;
  gateway_running: boolean;
  model?: string | null;
  provider?: string | null;
  has_env: boolean;
  skill_count: number;
  alias_path?: string | null;
}

export interface ProfilesResponse {
  ok: boolean;
  active: string;
  profiles: ProfileInfo[];
}

export interface ProfileCreateRequest {
  name: string;
  clone_from?: string | null;
  clone_config?: boolean;
  clone_all?: boolean;
  no_alias?: boolean;
}

export interface PluginInfo {
  id: string;
  name: string;
  path: string;
  description?: string | null;
  version?: string | null;
  enabled: boolean;
}

export interface PluginsResponse {
  ok: boolean;
  plugins: PluginInfo[];
}

export interface McpServersResponse {
  ok: boolean;
  servers: Record<string, Record<string, unknown>>;
}

export interface McpServerCreate {
  name: string;
  url?: string | null;
  command?: string | null;
  args?: string[];
  env?: Record<string, string>;
}

export interface DiagnosticsSummary {
  ok: boolean;
  spark_home: string;
  config_path: string;
  env_path: string;
  config_version?: number | null;
  platform: string;
  python: string;
  missing_required_env: string[];
  gateway_running: boolean;
  dashboard_auth: { token_file: string; configured: boolean };
  actions: AdminActionMeta[];
}

export interface ConversationDiagnosticsResponse {
  ok: boolean;
  session_id: string;
  resolved_session_id: string;
  active_turn_session_id: string | null;
  turn: {
    active: boolean;
    state?: string | null;
    phase?: string | null;
    status?: string | null;
    interrupt_requested: boolean;
    idle_for_seconds?: number | null;
    stale_after_seconds?: number | null;
    stream_revision?: number | null;
    stream_text_chars?: number | null;
  };
  timing_breakdown: Record<string, number>;
  message_count: number;
  notes: string[];
}

/** Payload shapes for /api/events chat.* topics */
export interface ChatTokenData {
  t: string;
}

export interface ChatToolStartData {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface ChatToolEndData {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result: string;
}

export interface ChatReasoningData {
  text: string;
}

export interface ChatStatusData {
  kind: string;
  message: string;
}

export interface ChatApprovalRequestedData {
  approval: {
    command?: string;
    description?: string;
    pattern_key?: string;
    pattern_keys?: string[];
  };
}

export type SubagentStatus =
  | "queued"
  | "starting"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "interrupted"
  | "stale"
  | string;

export interface SubagentEvent {
  id?: string;
  run_id?: string;
  subagent_id?: string;
  type?: string;
  kind?: string;
  role?: string;
  text?: string | null;
  content?: string | null;
  message?: string | null;
  status?: SubagentStatus;
  tool_name?: string | null;
  tool_call_id?: string | null;
  ts?: number;
  timestamp?: number;
  created_at?: number;
  data?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface SubagentRun {
  id: string;
  run_id?: string;
  subagent_id?: string;
  parent_session_id?: string | null;
  conversation_id?: string | null;
  child_session_id?: string | null;
  name?: string | null;
  task?: string | null;
  goal?: string | null;
  context?: string | null;
  status: SubagentStatus;
  summary?: string | null;
  error?: string | null;
  model?: string | null;
  started_at?: number | null;
  updated_at?: number | null;
  ended_at?: number | null;
  elapsed_seconds?: number | null;
  duration_seconds?: number | null;
  events?: SubagentEvent[];
  transcript?: SubagentEvent[];
  metadata?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface ConversationSubagentsResponse {
  session_id: string;
  subagents: SubagentRun[];
}

export interface ConversationSubagentResponse {
  session_id: string;
  subagent: SubagentRun;
}

export interface ConversationSubagentMessagesResponse {
  session_id: string;
  requested_session_id?: string;
  subagent_id: string;
  child_session_id?: string | null;
  messages: SessionMessage[];
  total: number;
  limit: number;
  offset?: number;
  include_tool_results?: boolean;
}

export interface ConversationSubagentInterruptResponse {
  ok: boolean;
  session_id: string;
  subagent_id: string;
  child_session_id?: string | null;
  status: SubagentStatus;
}

export type ChatSubagentEventData = Partial<SubagentRun> & {
  id?: string;
  run_id?: string;
  subagent_id?: string;
  event?: SubagentEvent;
  events?: SubagentEvent[];
  transcript?: SubagentEvent[];
};

export interface SessionsChangedData {
  action: "created" | "updated" | "deleted";
  session_id: string;
  session?: SessionInfo;
}

// ── Model info types ──────────────────────────────────────────────────

export interface ReasoningEffortResponse {
  effort: string;
  supported: boolean;
}

export interface ModelStatusResponse {
  smart_model: string;
  smart_provider: string;
  fast_model: string;
  fast_provider: string;
  multi_model_enabled: boolean;
  reasoning_effort: string;
  reasoning_supported: boolean;
}

export interface ModelSuggestionsResponse {
  smart: string[];
  fast: string[];
  smart_provider: string;
  fast_provider: string;
}

export interface ModelInfoResponse {
  model: string;
  provider: string;
  auto_context_length: number;
  config_context_length: number;
  effective_context_length: number;
  capabilities: {
    supports_tools?: boolean;
    supports_vision?: boolean;
    supports_reasoning?: boolean;
    context_window?: number;
    max_output_tokens?: number;
    model_family?: string;
  };
}

// ── OAuth provider types ────────────────────────────────────────────────

export interface OAuthProviderStatus {
  logged_in: boolean;
  source?: string | null;
  source_label?: string | null;
  token_preview?: string | null;
  expires_at?: string | null;
  has_refresh_token?: boolean;
  last_refresh?: string | null;
  error?: string;
}

export interface OAuthProvider {
  id: string;
  name: string;
  /** "pkce" (browser redirect + paste code), "device_code" (show code + URL),
   *  or "external" (delegated to a separate CLI like Claude Code or Qwen). */
  flow: "pkce" | "device_code" | "external";
  cli_command: string;
  docs_url: string;
  status: OAuthProviderStatus;
}

export interface OAuthProvidersResponse {
  providers: OAuthProvider[];
}

/** Discriminated union — the shape of /start depends on the flow. */
export type OAuthStartResponse =
  | {
      session_id: string;
      flow: "pkce";
      auth_url: string;
      expires_in: number;
    }
  | {
      session_id: string;
      flow: "device_code";
      // null while OpenAI's (often-slow) device-auth call is still in flight;
      // the UI then polls until the code arrives.
      status?: "starting" | "polling";
      user_code: string | null;
      verification_url: string;
      expires_in: number;
      poll_interval: number;
    };

export interface OAuthSubmitResponse {
  ok: boolean;
  status: "approved" | "error";
  message?: string;
}

export interface OAuthPollResponse {
  session_id: string;
  status: "pending" | "approved" | "denied" | "expired" | "error";
  error_message?: string | null;
  expires_at?: number | null;
  // Populated once the device-auth call returns (may lag the /start response).
  user_code?: string | null;
  verification_url?: string | null;
}

// ── Workspace types ───────────────────────────────────────────────────────

export interface WorkspaceProject {
  slug: string;
  name: string;
  path: string;
  mtime: number;
  file_count: number;
}

export interface WorkspaceProjectsResponse {
  projects: WorkspaceProject[];
}

export interface ProjectTemplate {
  id: string;
  label: string;
  description: string;
  project_type: ProjectType;
  recommended: boolean;
  available: boolean;
  package_managers: PackageManager[];
  default_package_manager: PackageManager | null;
  supported_options: string[];
  recommended_skills: string[];
}

export type ProjectType =
  | "blank"
  | "static_website"
  | "web_application"
  | "design_project"
  | "productivity_workspace"
  | "video_project";

export type PackageManager = "pnpm" | "npm" | "yarn" | "bun";

export interface ProjectTypeGroup {
  id: ProjectType;
  label: string;
  starters: ProjectTemplate[];
}

export interface ProjectTemplatesResponse {
  project_types: ProjectTypeGroup[];
  templates: ProjectTemplate[];
}

export interface ProjectCreateRequest {
  name: string;
  template?: string;
  project_type?: ProjectType;
  starter_stack?: string;
  package_manager?: PackageManager;
  init_git?: boolean;
  initial_commit?: boolean;
  ai_skills_mode?: "recommended" | "manual";
  selected_skills?: string[];
  dev_tools?: string[];
  integrations?: string[];
}

// ── Canvas types ──────────────────────────────────────────────────────────
export type CanvasScope = "global" | "project";

export interface CanvasViewport {
  x: number;
  y: number;
  zoom: number;
}

export interface CanvasDoc {
  id: string;
  name: string;
  scope: CanvasScope;
  slug: string | null;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  viewport: CanvasViewport;
  version: number;
  updatedAt?: string | null;
  revision?: string | null;
  expectedRevision?: string | null;
}

// React Flow node/edge shapes (loose — the canvas owns the concrete data types).
export interface CanvasNode {
  id: string;
  type?: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
  width?: number | null;
  height?: number | null;
  [key: string]: unknown;
}

export interface CanvasEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
  [key: string]: unknown;
}

export interface CanvasSummary {
  id: string;
  name: string;
  scope: CanvasScope;
  slug: string | null;
  updatedAt: string;
  revision?: string | null;
  error?: string | null;
}

export interface CanvasListResponse {
  canvases: CanvasSummary[];
}

// ── Workflow engine types ─────────────────────────────────────────────────
export interface WorkflowNodeType {
  type: string;
  category: "trigger" | "action" | "control" | "agent" | "io" | "display";
  label: string;
  emoji?: string;
  tool?: string;
  toolset?: string;
  description?: string;
  schema?: { properties?: Record<string, JsonSchemaProp>; required?: string[] };
}

export interface JsonSchemaProp {
  type?: string;
  description?: string;
  enum?: unknown[];
  default?: unknown;
  [key: string]: unknown;
}

export interface WorkflowItem {
  json: Record<string, unknown>;
  binary?: Record<string, unknown>;
}

export interface WorkflowNodeResult {
  nodeId: string;
  status: "success" | "error" | "skipped";
  items: WorkflowItem[];
  error: string | null;
  durationMs: number;
}

export interface WorkflowRunResult {
  executionId: string;
  status: "success" | "error";
  error: string | null;
  nodes: WorkflowNodeResult[];
}

export interface WorkflowExecutionSummary {
  id: string;
  canvas_id: string;
  scope: string;
  slug: string | null;
  status: string;
  error: string | null;
  started_at: number;
  finished_at: number;
  trigger: string;
}

export interface WorkflowExecutionDetail extends WorkflowExecutionSummary {
  nodes: WorkflowNodeResult[];
}

export interface WorkflowTrigger {
  id: string;
  canvas_id: string;
  node_id: string;
  kind: string;
  enabled: boolean;
  secret?: string | null;
  schedule?: string | null;
  path?: string | null;
  next_run_at?: number | null;
  last_run_at?: number | null;
}

export interface FileListEntry {
  name: string;
  path: string;
  type: "file" | "dir";
}

export interface FileListResponse {
  path: string;
  entries: FileListEntry[];
}

export interface WorkspaceFileNode {
  name: string;
  path: string;
  type: "file" | "dir";
  size?: number;
  mtime?: number;
  mime?: string;
  children?: WorkspaceFileNode[];
}

export interface WorkspaceTreeResponse {
  slug: string;
  path: string;
  tree: WorkspaceFileNode[];
}

export interface SlashCommand {
  name: string;
  description: string;
  category: string;
  aliases?: string[];
  args_hint?: string | null;
}

export interface WorkspaceFileContent {
  path: string;
  content: string;
  mime: string;
  size: number;
}

export interface WorkspaceTerminalRunStart {
  run_id: string;
  status: "queued" | "running" | "done" | "failed" | "stopped";
  cwd: string;
}

export type WorkspaceTerminalEvent =
  | { type: "state"; status: string; cwd?: string }
  | { type: "output"; stream?: string; text: string }
  | { type: "done"; status: string; exit_code: number | null };

export interface WorkspacePreviewStatus {
  slug: string;
  status: "starting" | "running" | "stopped" | "failed";
  url: string | null;
  command: string | null;
  port: number | null;
  kind: string | null;
  error: string | null;
  started_at: number | null;
  updated_at: number | null;
}

export interface WorkspacePreviewLog {
  ts: number;
  type: "log";
  stream: string;
  text: string;
}

export interface WorkspaceGitFile {
  path: string;
  status: "added" | "deleted" | "modified";
  adds: number | null;
  dels: number | null;
}

export interface WorkspaceGitStatus {
  is_repo: boolean;
  branch: string | null;
  files: WorkspaceGitFile[];
  total_adds: number;
  total_dels: number;
}

export type WorkspacePreviewEvent =
  | ({ type: "state" } & WorkspacePreviewStatus)
  | WorkspacePreviewLog
  | { type: "refresh"; ts: number; reason?: string };

export interface MemoryTargetPayload {
  target: string;
  entries: string[];
  entry_count: number;
  chars: number;
  limit: number;
  percent: number;
}

export interface MemoryListResponse {
  targets: Record<string, MemoryTargetPayload>;
}

export interface StreamBrowserInput {
  type:
    | "click"
    | "rightclick"
    | "scroll"
    | "type"
    | "key"
    | "back"
    | "forward"
    | "upload"
    | "clipboard-write"
    | "clipboard-read"
    | "copy"
    | "paste";
  x?: number;
  y?: number;
  dx?: number;
  dy?: number;
  text?: string;
  key?: string;
  button?: "left" | "right" | "middle";
  files?: string[];
}

export interface StreamBrowserTab {
  id: string;
  title: string;
  url: string;
  active: boolean;
}

export interface StreamBrowserDownload {
  name: string;
  size: number;
  mtime: number;
}

export interface BrowserActionLogEntry {
  ts: number;
  action: string;
  status: string;
  task_id?: string | null;
  detail?: Record<string, unknown>;
}

export interface StreamBrowserConsoleEntry {
  seq: number;
  ts: number;
  kind: "console" | "network" | "exception";
  level: string;
  text: string;
  detail?: Record<string, unknown>;
}

export interface StreamBrowserPickedElement {
  selector?: string;
  tag?: string;
  role?: string;
  name?: string;
  text?: string;
  rect?: { x: number; y: number; width: number; height: number };
  url?: string;
}

export interface WorkspacePreviewSnapshot {
  slug: string;
  url: string | null;
  title: string;
  text: string;
  html_length: number;
}

export interface GoogleSetupInfo {
  redirect_uri: string;
  scopes: string[];
  configured: boolean;
  config_keys: { client_id: string; client_secret: string };
  console_url: string;
  client_type: string;
  error?: string;
}

export interface ArtifactInfo {
  id: string;
  name: string;
  type: "image" | "file" | "link";
  project_slug: string;
  project_name: string;
  path: string;
  url: string;
  size: number;
  mtime: number;
  mime: string;
}

export interface ArtifactsResponse {
  artifacts: ArtifactInfo[];
  counts: { all: number; images: number; files: number; links: number };
}

export interface MessagingField {
  key: string;
  label: string;
  description: string;
  type: "text" | "secret" | "bool" | "number" | string;
  placeholder: string;
  set: boolean;
  value: string;
}

export interface MessagingPlatform {
  id: string;
  name: string;
  description: string;
  help_text: string;
  setup_guide_url: string;
  enabled: boolean;
  configured: boolean;
  runtime: unknown;
  fields: {
    required: MessagingField[];
    recommended: MessagingField[];
    advanced: MessagingField[];
  };
  gateway_running?: boolean;
  saved?: string[];
  restart?: { ok: boolean; running: boolean; detail: string };
}

export interface MessagingPlatformsResponse {
  platforms: MessagingPlatform[];
  gateway_running: boolean;
}

export interface ConnectorStatus {
  id: string;
  name: string;
  description?: string;
  icon?: string;
  transport?: "cli" | "mcp" | "skill" | string;
  scopes?: string[];
  skills?: string[];
  toolsets?: string[];
  capabilities?: string[];
  docs_url?: string;
  kind?: "mcp" | "oauth" | "cli" | "api_key" | string;
  api_key_url?: string;
  primary_env_var?: string;
  env_vars?: string[];
  setup_steps?: string[];
  connected: boolean;
  configured: boolean;
  state?: string;
  detail?: string;
  account?: string | null;
  status?: {
    state: string;
    detail?: string;
    account?: string | null;
    scopes?: string[];
    extra?: {
      installed?: boolean;
      env_vars?: string[];
      cli?: string | null;
      config_paths?: string[];
      setup_steps?: string[];
      auth_type?: "oauth" | "api_key" | "multi_env" | "cli" | string;
      auth_url?: string;
      api_key_url?: string;
      primary_env_var?: string;
      oauth_configured?: boolean;
      server_name?: string;
      server_url?: string;
      connect_state?: string;
      connect_error?: string;
      cli_sync?: {
        synced?: boolean;
        reason?: string;
        detail?: string;
        host?: string;
      };
      [key: string]: unknown;
    };
  };
  email?: string | null;
  name_display?: string | null;
  picture?: string | null;
  gmail_read?: { connected: boolean; email?: string | null };
  error?: string;
}

export interface CliToolInfo {
  id: string;
  name: string;
  cli: string;
  detected: boolean;
  path: string | null;
  install_hint: string;
}
