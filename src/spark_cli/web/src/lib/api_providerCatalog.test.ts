import { afterEach, expect, it, vi } from "vitest";
import { getProviderCatalog } from "./api_providerCatalog";

afterEach(() => vi.unstubAllGlobals());

it("reads profile metadata through the existing authenticated transport without discovery", async () => {
  vi.stubGlobal("localStorage", { getItem: (key: string) => key === "spark_dashboard_token" ? "fixture-token" : null });
  const fixture = { schema_version: 1, selected_provider: "fixture", providers: [{
    id: "fixture", label: "New fixture", credential: { mechanism: "none", env_vars: [], configured: false },
    base_url: { policy: "editable", default: "" }, availability: "unknown", capabilities: { tools: "unknown" },
  }] };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture), { headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  expect(await getProviderCatalog()).toEqual(fixture);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/api/providers/catalogue");
  expect(fetch.mock.calls[0][1].headers.get("Authorization")).toBe("Bearer fixture-token");
});

it("rejects metadata from a retired backend connection", async () => {
  const { setDashboardToken } = await import("./apiHelpers");
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: vi.fn() });
  let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((done) => { resolve = done; })));
  const request = getProviderCatalog();
  setDashboardToken("replacement-fixture-token");
  resolve(new Response(JSON.stringify({ providers: [], selected_provider: "retired" })));
  await expect(request).rejects.toThrow("Provider catalogue connection changed");
});
