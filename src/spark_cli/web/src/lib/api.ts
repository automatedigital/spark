/** Spark web API client.
 *
 * Transport lives in apiHelpers.ts, response shapes in apiTypes.ts, and the
 * larger endpoint families in the api_*.ts modules composed below.
 * Everything is re-exported here so existing imports keep working.
 */

export * from "./apiHelpers";
export * from "./apiTypes";

import {
  authHeaders,
  fetchJSON,
  mediaFileUrl,
} from "./apiHelpers";
import { sessionApi } from "./api_session";
import { skillApi } from "./api_skill";
import { cronApi } from "./api_cron";
import { kanbanApi } from "./api_kanban";
import { workspaceApi } from "./api_workspace";
import { canvasApi } from "./api_canvas";
import { memoryApi } from "./api_memory";
import { connectorApi } from "./api_connector";
import { workflowApi } from "./api_workflow";

import type {
  AnalyticsResponse,
  ArtifactsResponse,
  ConnectorStatus,
  ConversationDiagnosticsResponse,
  ConversationSubagentInterruptResponse,
  ConversationSubagentMessagesResponse,
  ConversationSubagentResponse,
  ConversationSubagentsResponse,
  DashboardAuthInfo,
  DiagnosticsSummary,
  FileListResponse,
  GoogleSetupInfo,
  LogsResponse,
  MessagingPlatform,
  MessagingPlatformsResponse,
  ProfileCreateRequest,
  ProfileInfo,
  ProfilesResponse,
  ProjectTemplatesResponse,
  ReasoningEffortResponse,
  SlashCommand,
  StatusResponse,
  ToolsetInfo,
  WebApprovalSubmitResponse,
  WebPendingActionSubmitResponse,
  WebPendingActionsResponse,
  WebPlanResponse,
  WebTurnOutcome,
  WebTurnOutcomesResponse,
} from "./apiTypes";

import { configApi } from "./api_config";
import { modelApi } from "./api_model";
import { adminApi } from "./api_admin";
import { gatewayApi } from "./api_gateway";
import { pluginApi } from "./api_plugin";
import { mcpApi } from "./api_mcp";
import { providerApi } from "./api_provider";

import { browserApi } from "./api_browser";

import { envApi } from "./api_env";

export const api = {
  ...adminApi,
  ...browserApi,
  ...canvasApi,
  ...configApi,
  ...connectorApi,
  ...cronApi,
  ...envApi,
  ...gatewayApi,
  ...kanbanApi,
  ...mcpApi,
  ...memoryApi,
  ...modelApi,
  ...pluginApi,
  ...providerApi,
  ...sessionApi,
  ...skillApi,
  ...workflowApi,
  ...workspaceApi,
  getStatus: () => fetchJSON<StatusResponse>("/api/status"),
  getOnboardingStatus: () =>
    fetchJSON<{ needs_onboarding: boolean; has_model: boolean; has_api_key: boolean }>(
      "/api/onboarding/status",
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
  getDefaults: () => fetchJSON<Record<string, unknown>>("/api/config/defaults"),
  getSchema: () => fetchJSON<{ fields: Record<string, unknown>; category_order: string[] }>("/api/config/schema"),
  getReasoningEffort: () => fetchJSON<ReasoningEffortResponse>("/api/model/reasoning"),
  setReasoningEffort: (effort: string) =>
    fetchJSON<{ effort: string; ok: boolean }>("/api/model/reasoning", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ effort }),
    }),
  getToolsets: () => fetchJSON<ToolsetInfo[]>("/api/tools/toolsets"),

  // Session search (FTS5)
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
  interruptConversation: (sessionId: string, message?: string) =>
    fetchJSON<{ ok: boolean; session_id: string }>(
      `/api/conversations/${encodeURIComponent(sessionId)}/interrupt`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: message ?? null }),
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
    actionId?: string,
  ) =>
    fetchJSON<WebApprovalSubmitResponse>(
      `/api/conversations/${encodeURIComponent(sessionId)}/approval`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          choice,
          resolve_all: resolveAll,
          ...(actionId ? { action_id: actionId } : {}),
        }),
      },
    ),
  getConversationTurnOutcome: (sessionId: string) =>
    fetchJSON<WebTurnOutcome | null>(
      `/api/conversations/${encodeURIComponent(sessionId)}/turn-outcome`,
    ),
  getConversationTurnOutcomes: (sessionId: string) =>
    fetchJSON<WebTurnOutcomesResponse>(
      `/api/conversations/${encodeURIComponent(sessionId)}/turn-outcomes`,
    ),
  getConversationPlan: (sessionId: string) =>
    fetchJSON<WebPlanResponse>(
      `/api/conversations/${encodeURIComponent(sessionId)}/plan`,
    ),
  getConversationPendingActions: (sessionId: string) =>
    fetchJSON<WebPendingActionsResponse>(
      `/api/conversations/${encodeURIComponent(sessionId)}/pending-actions`,
    ),
  submitConversationInput: (sessionId: string, actionId: string, response: string) =>
    fetchJSON<WebPendingActionSubmitResponse>(
      `/api/conversations/${encodeURIComponent(sessionId)}/input`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_id: actionId, response }),
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
  getCodexUsage: () =>
    fetchJSON<{ available: boolean; reason?: string; data?: Record<string, unknown> }>("/api/model/codex-usage"),

  // OAuth provider management
  openExternalUrl: (url: string) =>
    fetchJSON<{ opened: boolean }>(`/api/system/open-external`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }),

  // Slash commands list (gateway-available only)
  getCommands: () => fetchJSON<SlashCommand[]>("/api/commands"),

  // Workspace
  listProjectTemplates: () =>
    fetchJSON<ProjectTemplatesResponse>("/api/workspace/project-templates"),
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
  detectDevServers: (slug: string) =>
    fetchJSON<{ slug: string; servers: { url: string; port: number }[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/detect-servers`,
    ),
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
  getGoogleStatus: () =>
    fetchJSON<ConnectorStatus>("/api/connectors/google/status"),
  getGoogleSetup: () =>
    fetchJSON<GoogleSetupInfo>("/api/connectors/google/setup"),
  connectGoogle: () =>
    fetchJSON<{ auth_url?: string; error?: string; message?: string }>(
      "/api/connectors/google/connect",
      { method: "POST" },
    ),
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
};


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
