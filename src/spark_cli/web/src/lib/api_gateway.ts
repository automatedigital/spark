/** gateway endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  AdminRunStartResponse,
} from "./apiTypes";

export const gatewayApi = {
  controlGateway: (action: string, confirm = false) =>
    fetchJSON<AdminRunStartResponse>("/api/gateway/control", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, confirm }),
    }),
};
