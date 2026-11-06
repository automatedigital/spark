import { fetchJSON } from "./apiHelpers";

export interface McpReadiness {
  state: "unknown" | "testing" | "ready" | "failed";
  last_test_at: number | null;
  duration_ms: number | null;
  tool_count: number | null;
  error: string | null;
  run_id: string | null;
}
export const getMcpReadiness = () => fetchJSON<{
  readiness: Record<string, McpReadiness>;
}>("/api/mcp/servers");
