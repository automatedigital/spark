/** admin endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  AdminActionsResponse,
  AdminRun,
  AdminRunStartResponse,
  GatewayAdminStatus,
} from "./apiTypes";

export const adminApi = {
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
};
