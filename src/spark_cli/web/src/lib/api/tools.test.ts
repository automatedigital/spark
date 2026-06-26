import { describe, expect, it } from "vitest";
import { createToolsApi } from "./tools";
import type { FetchJSON } from "./model";

function recorder() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchJSON = (async <T>(url: string, init?: RequestInit): Promise<T> => {
    calls.push({ url, init });
    return {} as T;
  }) satisfies FetchJSON;
  return { api: createToolsApi(fetchJSON), calls };
}

describe("tools api client", () => {
  it("keeps tools and command read endpoints on their existing paths", async () => {
    const { api, calls } = recorder();

    await api.getSkills();
    await api.getToolsets();
    await api.getCommands();

    expect(calls.map((call) => call.url)).toEqual([
      "/api/skills",
      "/api/tools/toolsets",
      "/api/commands",
    ]);
  });

  it("preserves mutation request bodies", async () => {
    const { api, calls } = recorder();

    await api.toggleSkill("agent-browser", true);
    await api.setupOnboardingSkills("recommended");

    expect(calls).toEqual([
      {
        url: "/api/skills/toggle",
        init: {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: "agent-browser", enabled: true }),
        },
      },
      {
        url: "/api/onboarding/skills",
        init: {
          method: "POST",
          body: JSON.stringify({ mode: "recommended" }),
          headers: { "Content-Type": "application/json" },
        },
      },
    ]);
  });
});
