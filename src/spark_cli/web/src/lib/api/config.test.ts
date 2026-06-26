import { describe, expect, it } from "vitest";
import { createConfigApi, type WithSessionToken } from "./config";
import type { FetchJSON } from "./model";

function recorder() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchJSON = (async <T>(url: string, init?: RequestInit): Promise<T> => {
    calls.push({ url, init });
    return {} as T;
  }) satisfies FetchJSON;
  const withSessionToken = ((run) => run("session-token")) satisfies WithSessionToken;
  return { api: createConfigApi(fetchJSON, withSessionToken), calls };
}

describe("config api client", () => {
  it("keeps config and env read endpoints on their existing paths", async () => {
    const { api, calls } = recorder();

    await api.getConfig();
    await api.getDefaults();
    await api.getSchema();
    await api.getConfigRaw();
    await api.getEnvVars();

    expect(calls.map((call) => call.url)).toEqual([
      "/api/config",
      "/api/config/defaults",
      "/api/config/schema",
      "/api/config/raw",
      "/api/env",
    ]);
  });

  it("preserves config and env mutation request bodies", async () => {
    const { api, calls } = recorder();

    await api.saveConfig({ model: "gpt-5" });
    await api.saveConfigRaw("model: gpt-5\n");
    await api.setEnvVar("OPENAI_API_KEY", "sk-test");
    await api.deleteEnvVar("OLD_KEY");

    expect(calls).toEqual([
      {
        url: "/api/config",
        init: {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ config: { model: "gpt-5" } }),
        },
      },
      {
        url: "/api/config/raw",
        init: {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ yaml_text: "model: gpt-5\n" }),
        },
      },
      {
        url: "/api/env",
        init: {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: "OPENAI_API_KEY", value: "sk-test" }),
        },
      },
      {
        url: "/api/env",
        init: {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: "OLD_KEY" }),
        },
      },
    ]);
  });

  it("reveals env vars with a session-token authorization header", async () => {
    const { api, calls } = recorder();

    await api.revealEnvVar("OPENAI_API_KEY");

    expect(calls).toEqual([
      {
        url: "/api/env/reveal",
        init: {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer session-token",
          },
          body: JSON.stringify({ key: "OPENAI_API_KEY" }),
        },
      },
    ]);
  });
});
