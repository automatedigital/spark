/** workspace endpoints, split out of api.ts. */

import {
  authHeaders,
  fetchJSON,
  sseUrl,
} from "./apiHelpers";
import type {
  BrowserActionLogEntry,
  FileListResponse,
  PaginatedSessions,
  ProjectCreateRequest,
  WorkspaceFileContent,
  WorkspaceGitStatus,
  WorkspacePreviewLog,
  WorkspacePreviewSnapshot,
  WorkspacePreviewStatus,
  WorkspaceProjectsResponse,
  WorkspaceTerminalRunStart,
  WorkspaceTreeResponse,
} from "./apiTypes";

export const workspaceApi = {
  listWorkspaceProjects: () =>
    fetchJSON<WorkspaceProjectsResponse>("/api/workspace/projects"),
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
  listWorkspaceDir: (slug: string, path = "", showHidden = false) => {
    const qs = new URLSearchParams();
    if (path) qs.set("path", path);
    if (showHidden) qs.set("show_hidden", "true");
    const query = qs.toString();
    return fetchJSON<FileListResponse>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/list${query ? `?${query}` : ""}`,
    );
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
  refreshWorkspacePreview: (slug: string) =>
    fetchJSON<{ ok: boolean; slug: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/refresh`,
      { method: "POST" },
    ),

  // ── Streamed server-side browser (WebUI path) ──
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
};
