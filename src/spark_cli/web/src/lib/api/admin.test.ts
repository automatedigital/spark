import { describe, expect, it } from "vitest";
import { createAdminApi } from "./admin";
import type { FetchJSON } from "./model";

function recorder() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchJSON = (async <T>(url: string, init?: RequestInit): Promise<T> => {
    calls.push({ url, init });
    return {} as T;
  }) satisfies FetchJSON;
  return { api: createAdminApi(fetchJSON), calls };
}

describe("admin api client", () => {
  it("keeps admin read endpoints on their existing paths", async () => {
    const { api, calls } = recorder();

    await api.getAdminActions();
    await api.getAdminRun("run/id");
    await api.getGatewayAdminStatus();
    await api.getProfiles();
    await api.getPlugins();
    await api.getMcpServers();
    await api.getDiagnosticsSummary();
    await api.checkForUpdate();
    await api.checkMacUpdate();

    expect(calls.map((call) => call.url)).toEqual([
      "/api/admin/actions",
      "/api/admin/actions/runs/run%2Fid",
      "/api/gateway/status",
      "/api/profiles",
      "/api/plugins",
      "/api/mcp/servers",
      "/api/diagnostics/summary",
      "/api/update/check",
      "/api/mac/update/check",
    ]);
  });

  it("preserves admin mutation paths and request bodies", async () => {
    const { api, calls } = recorder();

    await api.runAdminAction("update.run", { force: true }, true);
    await api.controlGateway("restart", true);
    await api.createProfile({ name: "demo" });
    await api.deleteProfile("demo", true);
    await api.addMcpServer({ name: "docs", command: "npx" });
    await api.runMacUpdate();

    expect(calls).toEqual([
      {
        url: "/api/admin/actions/update.run",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ args: { force: true }, confirm: true }),
        },
      },
      {
        url: "/api/gateway/control",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "restart", confirm: true }),
        },
      },
      {
        url: "/api/profiles",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: "demo" }),
        },
      },
      {
        url: "/api/profiles/demo?confirm=true",
        init: { method: "DELETE" },
      },
      {
        url: "/api/mcp/servers",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: "docs", command: "npx" }),
        },
      },
      {
        url: "/api/mac/update/run",
        init: { method: "POST" },
      },
    ]);
  });
});
