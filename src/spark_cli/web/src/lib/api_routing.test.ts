import { afterEach, expect, it, vi } from "vitest";
import { getRecordedRoutes, getRoutingSettings } from "./api_routing";

afterEach(() => vi.unstubAllGlobals());

it("reads recorded turn data without submitting a model request", async () => {
  vi.stubGlobal("localStorage", { getItem: (key: string) => key === "spark_dashboard_token" ? "synthetic-token" : null });
  const fixture = { schema_version: 1, turns: [{ turn_id: "actual", model: "old-model", routing_reason: "explicit_model_pinned" }] };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture)));
  vi.stubGlobal("fetch", fetch);
  const controller = new AbortController();
  expect(await getRecordedRoutes("thread/a", controller.signal)).toEqual(fixture);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch.mock.calls[0][0]).toBe("/api/model/routing/turns/thread%2Fa");
  expect(fetch.mock.calls[0][1].signal).toBe(controller.signal);
  expect(fetch.mock.calls[0][1].cache).toBe("no-store");
  expect(fetch.mock.calls[0][1].headers.get("Authorization")).toBe("Bearer synthetic-token");
});

it("rejects settings from a retired backend connection", async () => {
  const { setDashboardToken } = await import("./apiHelpers");
  vi.stubGlobal("localStorage", { getItem: () => null, setItem: vi.fn() });
  let resolve!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>((done) => { resolve = done; })));
  const pending = getRoutingSettings();
  setDashboardToken("replacement-token");
  resolve(new Response(JSON.stringify({ roles: {}, selection: "auto" })));
  await expect(pending).rejects.toThrow("Routing connection changed");
});

it("preserves unknown decisions rather than constructing a new explanation", async () => {
  vi.stubGlobal("localStorage", { getItem: () => null });
  const fixture = { schema_version: 1, turns: [{ turn_id: "legacy", status: "unknown", model: null, routing_decision: null, routing_reason: null }] };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(fixture))));
  expect(await getRecordedRoutes("legacy")).toEqual(fixture);
});

it("explains actual stored reasons and never invents a fallback for missing data", async () => {
  const { describeRecordedRoute } = await import("./api_routing");
  const unknown = { turn_id: "t", session_id: "s", status: "unknown" as const, model: null, provider: null, role: null, routing_reason: null, routing_decision: null };
  expect(describeRecordedRoute(unknown)).toContain("unknown");
  expect(describeRecordedRoute(unknown)).not.toContain("fallback");
  expect(describeRecordedRoute({ ...unknown, status: "recorded", routing_reason: "explicit_model_pinned" })).toBe("Your explicit model choice was used.");
  expect(describeRecordedRoute({ ...unknown, status: "recorded", routing_reason: "auto_fallback:fast:runtime_unavailable" })).toContain("primary route was used");
  expect(describeRecordedRoute({ ...unknown, status: "recorded", routing_reason: "auto:lead:high_risk_floor" })).toContain("high-risk");
});
