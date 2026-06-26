import type {
  AdminActionsResponse,
  AdminRun,
  AdminRunStartResponse,
  DiagnosticsSummary,
  GatewayAdminStatus,
  McpServerCreate,
  McpServersResponse,
  PluginsResponse,
  ProfileCreateRequest,
  ProfileInfo,
  ProfilesResponse,
} from "../api";
import type { FetchJSON } from "./model";

export interface MacUpdateCheckResponse {
  update_available: boolean;
  latest_version: string | null;
  current_version: string | null;
  download_url: string | null;
  release_url: string | null;
  release_notes?: string | null;
  release_name?: string | null;
  published_at?: string | null;
}

export function createAdminApi(fetchJSON: FetchJSON) {
  return {
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
    checkForUpdate: () =>
      fetchJSON<{ update_available: boolean; commits_behind: number | null }>("/api/update/check"),
    checkMacUpdate: () => fetchJSON<MacUpdateCheckResponse>("/api/mac/update/check"),
    runMacUpdate: () =>
      fetchJSON<{ ok: boolean; path: string; latest_version: string | null }>("/api/mac/update/run", {
        method: "POST",
      }),
  };
}

export type AdminApi = ReturnType<typeof createAdminApi>;
