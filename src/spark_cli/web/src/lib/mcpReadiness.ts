import { fetchJSON } from "./apiHelpers";
import type { McpServerCreate } from "./apiTypes";

export interface McpReadiness {
  state: "unknown" | "testing" | "ready" | "failed";
  last_test_at: number | null;
  duration_ms: number | null;
  tool_count: number | null;
  error: string | null;
  run_id: string | null;
}
export interface McpReadinessResponse {
  ok: boolean;
  servers: Record<string, { configured: boolean }>;
  readiness: Record<string, McpReadiness>;
}
export const getMcpReadiness = () => fetchJSON<McpReadinessResponse>("/api/mcp/servers");
export const saveMcpConfiguration = (body: McpServerCreate & { headers?: Record<string, string> }) =>
  fetchJSON("/api/mcp/servers", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
