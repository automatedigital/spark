/** connector endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  CliToolInfo,
  ConnectorStatus,
} from "./apiTypes";

export const connectorApi = {
  listConnectors: () =>
    fetchJSON<ConnectorStatus[]>("/api/connectors"),
  getConnectorStatus: (connectorId: string) =>
    fetchJSON<ConnectorStatus>(`/api/connectors/${encodeURIComponent(connectorId)}/status`),
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
  getConnectorCliTools: () =>
    fetchJSON<CliToolInfo[]>("/api/connectors/cli-tools"),

  // ── Workflows (Canvas execution engine) ──
};
