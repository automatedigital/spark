const BASE = "";

const DASHBOARD_TOKEN_KEY = "spark_dashboard_token";

// Ephemeral session token for protected endpoints (reveal).
// Fetched once on first reveal request and cached in memory.
let _sessionToken: string | null = null;

export function getDashboardToken(): string | null {
  if (typeof localStorage === "undefined") return null;
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
  return `/api/workspace/projects/${encodeURIComponent(slug)}/raw-file?${qs}`;
}

/** Append dashboard auth for EventSource (no custom headers support). */
export function sseUrl(path: string): string {
  const t = getDashboardToken();
  if (!t) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}dashboard_token=${encodeURIComponent(t)}`;
}

function authHeaders(base?: HeadersInit): Headers {
  const h = new Headers(base);
  const tok = getDashboardToken();
  if (tok) h.set("Authorization", `Bearer ${tok}`);
  return h;
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers: authHeaders(init?.headers),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

async function getSessionToken(): Promise<string> {
  if (_sessionToken) return _sessionToken;
  const resp = await fetchJSON<{ token: string }>("/api/auth/session-token");
  _sessionToken = resp.token;
  return _sessionToken;
}

export const api = {
  getStatus: () => fetchJSON<StatusResponse>("/api/status"),
  getSessions: (limit = 20, offset = 0, source?: string) => {
    const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (source) qs.set("source", source);
    return fetchJSON<PaginatedSessions>(`/api/sessions?${qs.toString()}`);
  },
  getSessionMessages: (id: string) =>
    fetchJSON<SessionMessagesResponse>(`/api/sessions/${encodeURIComponent(id)}/messages`),
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
  revealEnvVar: async (key: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ key: string; value: string }>("/api/env/reveal", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ key }),
    });
  },

  // Cron jobs
  getCronJobs: () => fetchJSON<CronJob[]>("/api/cron/jobs"),
  createCronJob: (job: { prompt: string; schedule: string; name?: string; deliver?: string }) =>
    fetchJSON<CronJob>("/api/cron/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
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
  postConversation: (message: string, model?: string) =>
    fetchJSON<{ session_id: string; ok: boolean }>("/api/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, model }),
    }),
  postConversationMessage: (sessionId: string, message: string) =>
    fetchJSON<{ session_id: string; ok: boolean }>(
      `/api/conversations/${encodeURIComponent(sessionId)}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
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

  // OAuth provider management
  getOAuthProviders: () =>
    fetchJSON<OAuthProvidersResponse>("/api/providers/oauth"),
  disconnectOAuthProvider: async (providerId: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ ok: boolean; provider: string }>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}`,
      {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      },
    );
  },
  startOAuthLogin: async (providerId: string) => {
    const token = await getSessionToken();
    return fetchJSON<OAuthStartResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/start`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: "{}",
      },
    );
  },
  submitOAuthCode: async (providerId: string, sessionId: string, code: string) => {
    const token = await getSessionToken();
    return fetchJSON<OAuthSubmitResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/submit`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ session_id: sessionId, code }),
      },
    );
  },
  pollOAuthSession: (providerId: string, sessionId: string) =>
    fetchJSON<OAuthPollResponse>(
      `/api/providers/oauth/${encodeURIComponent(providerId)}/poll/${encodeURIComponent(sessionId)}`,
    ),
  cancelOAuthSession: async (sessionId: string) => {
    const token = await getSessionToken();
    return fetchJSON<{ ok: boolean }>(
      `/api/providers/oauth/sessions/${encodeURIComponent(sessionId)}`,
      {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      },
    );
  },

  // Slash commands list (gateway-available only)
  getCommands: () => fetchJSON<SlashCommand[]>("/api/commands"),

  // Workspace
  listWorkspaceProjects: () =>
    fetchJSON<WorkspaceProjectsResponse>("/api/workspace/projects"),

  createWorkspaceProject: (name: string) =>
    fetchJSON<{ ok: boolean; slug: string; name: string; path: string }>("/api/workspace/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),

  getWorkspaceFileTree: (slug: string) =>
    fetchJSON<WorkspaceTreeResponse>(`/api/workspace/projects/${encodeURIComponent(slug)}/tree`),

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

  deleteWorkspaceFile: (slug: string, path: string) => {
    const qs = new URLSearchParams({ path });
    return fetchJSON<{ ok: boolean; deleted: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/file?${qs}`,
      { method: "DELETE" },
    );
  },

  runWorkspaceTerminalCommand: (slug: string, command: string) =>
    fetchJSON<WorkspaceTerminalRunStart>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/terminal/runs`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command }),
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

  startWorkspaceConversation: (slug: string, message: string, model?: string) =>
    fetchJSON<{ session_id: string; ok: boolean; source: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/conversations`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, model }),
      },
    ),

  listWorkspaceConversations: (slug: string, limit = 30, offset = 0) => {
    const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    return fetchJSON<PaginatedSessions>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/conversations?${qs}`,
    );
  },
};

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
  dashboard_auth?: {
    token_file: string;
    require_auth_nonlocal: boolean;
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
  role: "user" | "assistant" | "system" | "tool";
  content: string | null;
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

export interface SessionsChangedData {
  action: "created" | "updated" | "deleted";
  session_id: string;
  session?: SessionInfo;
}

// ── Model info types ──────────────────────────────────────────────────

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
      user_code: string;
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
