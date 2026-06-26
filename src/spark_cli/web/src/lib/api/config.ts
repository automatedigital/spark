import type { EnvVarInfo } from "../api";
import type { FetchJSON } from "./model";

export type WithSessionToken = <T>(run: (token: string) => Promise<T>) => Promise<T>;

export function createConfigApi(fetchJSON: FetchJSON, withSessionToken: WithSessionToken) {
  return {
    getConfig: () => fetchJSON<Record<string, unknown>>("/api/config"),
    getDefaults: () => fetchJSON<Record<string, unknown>>("/api/config/defaults"),
    getSchema: () =>
      fetchJSON<{ fields: Record<string, unknown>; category_order: string[] }>("/api/config/schema"),
    saveConfig: (config: Record<string, unknown>) =>
      fetchJSON<{ ok: boolean }>("/api/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config }),
      }),
    getConfigRaw: () => fetchJSON<{ yaml: string }>("/api/config/raw"),
    saveConfigRaw: (yaml_text: string) =>
      fetchJSON<{ ok: boolean }>("/api/config/raw", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml_text }),
      }),
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
  };
}

export type ConfigApi = ReturnType<typeof createConfigApi>;
