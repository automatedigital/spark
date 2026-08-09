/** plugin endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  AdminRunStartResponse,
  PluginsResponse,
} from "./apiTypes";

export const pluginApi = {
  getPlugins: () => fetchJSON<PluginsResponse>("/api/plugins"),
  runPluginAction: (action: string, name: string, confirm = false) =>
    fetchJSON<AdminRunStartResponse>(`/api/plugins/${encodeURIComponent(action)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, confirm }),
    }),
};
