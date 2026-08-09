/** mcp endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  AdminRunStartResponse,
  McpServerCreate,
  McpServersResponse,
} from "./apiTypes";

export const mcpApi = {
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
};
