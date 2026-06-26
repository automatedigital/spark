import type {
  ArtifactsResponse,
  BrowserActionLogEntry,
  FileListResponse,
  PaginatedSessions,
  ProjectTemplate,
  StreamBrowserConsoleEntry,
  StreamBrowserDownload,
  StreamBrowserInput,
  StreamBrowserPickedElement,
  StreamBrowserTab,
  WorkspaceFileContent,
  WorkspaceGitStatus,
  WorkspacePreviewLog,
  WorkspacePreviewSnapshot,
  WorkspacePreviewStatus,
  WorkspaceProjectsResponse,
  WorkspaceTerminalRunStart,
  WorkspaceTreeResponse,
} from "../api";
import type { FetchJSON } from "./model";
import type { SseUrlBuilder } from "./session";

export type AuthHeadersBuilder = () => Headers;
export type MediaFileUrlBuilder = (path: string) => string;

export function createProjectsApi(
  fetchJSON: FetchJSON,
  authHeaders: AuthHeadersBuilder,
  mediaFileUrl: MediaFileUrlBuilder,
  sseUrl: SseUrlBuilder,
) {
  return {
    listWorkspaceProjects: () =>
      fetchJSON<WorkspaceProjectsResponse>("/api/workspace/projects"),
    listProjectTemplates: () =>
      fetchJSON<{ templates: ProjectTemplate[] }>("/api/workspace/project-templates"),
    createWorkspaceProject: (name: string, template = "scratch") =>
      fetchJSON<{ ok: boolean; slug: string; name: string; path: string; template: string }>(
        "/api/workspace/projects",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, template }),
        },
      ),
    deleteWorkspaceProject: (slug: string) =>
      fetchJSON<{ ok: boolean; deleted: string }>(`/api/workspace/projects/${encodeURIComponent(slug)}`, {
        method: "DELETE",
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
    refreshWorkspacePreview: (slug: string) =>
      fetchJSON<{ ok: boolean; slug: string }>(
        `/api/workspace/projects/${encodeURIComponent(slug)}/preview/refresh`,
        { method: "POST" },
      ),
    streamBrowserNavigate: (slug: string, url: string, persistent = true) =>
      fetchJSON<{ slug: string; url: string; title: string }>(
        `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/navigate`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ url, persistent }),
        },
      ),
    streamBrowserFrameUrl: (slug: string, bust: number) =>
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/frame?t=${bust}`,
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
    streamBrowserViewport: (slug: string, width: number, height: number) =>
      fetchJSON<{ slug: string; width: number; height: number }>(
        `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/viewport`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ width, height }),
        },
      ),
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
    streamBrowserTakeoverState: (slug: string) =>
      fetchJSON<{ slug: string; paused: boolean; ts: number }>(
        `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/takeover`,
      ),
    streamBrowserTakeover: (slug: string, paused: boolean) =>
      fetchJSON<{ slug: string; paused: boolean }>(
        `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/takeover`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paused }),
        },
      ),
    streamBrowserPick: (slug: string, x: number, y: number) =>
      fetchJSON<{ slug: string; element: StreamBrowserPickedElement }>(
        `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/pick`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ x, y }),
        },
      ),
    streamBrowserScreenshot: (slug: string) =>
      fetchJSON<{ slug: string; url: string; png_base64: string; name: string }>(
        `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/screenshot`,
      ),
    streamBrowserRecord: (slug: string, frames = 12, interval = 0.4) =>
      fetchJSON<{ slug: string; name: string }>(
        `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/record`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ frames, interval }),
        },
      ),
    streamBrowserConsole: (slug: string, sinceSeq = 0) =>
      fetchJSON<{ slug: string; entries: StreamBrowserConsoleEntry[] }>(
        `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/console?since_seq=${sinceSeq}`,
      ),
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
    listArtifacts: (type: string = "all", limit = 200) =>
      fetchJSON<ArtifactsResponse>(
        `/api/artifacts?type=${encodeURIComponent(type)}&limit=${limit}`,
      ),
  };
}

export type ProjectsApi = ReturnType<typeof createProjectsApi>;
