/** env endpoints, split out of api.ts. */

import {
  fetchJSON,
  withSessionToken,
} from "./apiHelpers";
import type {
  EnvVarInfo,
} from "./apiTypes";

export const envApi = {
  getEnvVars: () => fetchJSON<Record<string, EnvVarInfo>>("/api/env"),
  setEnvVar: (key: string, value: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, value }),
    }),
  deleteEnvVar: (key: string) =>
    fetchJSON<{ ok: boolean }>("/api/env", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    }),
  revealEnvVar: (key: string) =>
    withSessionToken((token) =>
      fetchJSON<{ key: string; value: string }>("/api/env/reveal", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ key }),
      }),
    ),

  // Cron jobs
};
