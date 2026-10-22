import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { briefApi, contextApi, type ContextItem } from "./context";
import { setLocalConnection, setRemoteConnection } from "./apiHelpers";

const item: ContextItem = { id: "file/id", type: "file", source_path: "/fixture/café.txt", inclusion_mode: "full", scope: "pinned", size_bytes: 42 };
const session = "session/with spaces";
const root = "/api/sessions/session%2Fwith%20spaces";
const cases = [
  { name: "context GET", run: () => contextApi.listItems(session), path: `${root}/context`, method: "GET", body: undefined },
  { name: "context PUT", run: () => contextApi.upsertItem(session, item), path: `${root}/context/file%2Fid`, method: "PUT", body: item },
  { name: "context DELETE", run: () => contextApi.removeItem(session, item.id), path: `${root}/context/file%2Fid`, method: "DELETE", body: undefined },
  { name: "brief GET", run: () => briefApi.get(session), path: `${root}/brief`, method: "GET", body: undefined },
  { name: "brief PUT", run: () => briefApi.set(session, "Brief\ntext"), path: `${root}/brief`, method: "PUT", body: { text: "Brief\ntext" } },
  { name: "estimate", run: () => contextApi.estimateTokens({ sessionId: session, promptText: "Prompt", contextItems: [item] }), path: "/api/estimate-tokens", method: "POST", body: { session_id: session, prompt: "Prompt", context_items: [item] } },
  { name: "estimate without session", run: () => contextApi.estimateTokens({ promptText: "", contextItems: [] }), path: "/api/estimate-tokens", method: "POST", body: { session_id: null, prompt: "", context_items: [] } },
  { name: "summarize project file", run: () => contextApi.summarizeFile(item.source_path!, "project"), path: "/api/summarize-file", method: "POST", body: { path: item.source_path, workspace_slug: "project" } },
  { name: "summarize general file", run: () => contextApi.summarizeFile(item.source_path!), path: "/api/summarize-file", method: "POST", body: { path: item.source_path } },
];
beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  });
});
afterEach(() => vi.unstubAllGlobals());

for (const mode of ["local", "remote"]) {
  it.each(cases)(`${mode}: routes $name with compatible headers and body`, async ({ run, path, method, body }) => {
    if (mode === "remote") setRemoteConnection("https://fixture.invalid/spark/", "fixture-token");
    else setLocalConnection();
    const response = { ok: true, summary: "Fixture summary" };
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(response)));
    vi.stubGlobal("fetch", fetch);
    expect(await run()).toEqual(response);
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0];
    expect(url).toBe(`${mode === "remote" ? "https://fixture.invalid/spark" : ""}${path}`);
    expect(init.method ?? "GET").toBe(method);
    expect(init.headers.get("Content-Type")).toBe("application/json");
    expect(init.headers.get("Authorization")).toBe(mode === "remote" ? "Bearer fixture-token" : null);
    expect(init.body).toBe(body === undefined ? undefined : JSON.stringify(body));
  });
}

it("captures each selected backend and credential at dispatch during rapid switching", async () => {
  const pending: Array<() => void> = [];
  const fetch = vi.fn<(url: string, init: RequestInit) => Promise<Response>>(() => new Promise<Response>((resolve) => pending.push(() => resolve(new Response("{}")))));
  vi.stubGlobal("fetch", fetch);
  setRemoteConnection("https://a.invalid", "token-a");
  const a = contextApi.estimateTokens({ promptText: "A", contextItems: [] });
  setRemoteConnection("https://b.invalid", "token-b");
  const b = briefApi.set(session, "B");
  setLocalConnection();
  const local = contextApi.summarizeFile("/fixture/local.txt");
  expect(fetch.mock.calls.map(([url]) => url)).toEqual(["https://a.invalid/api/estimate-tokens", `https://b.invalid${root}/brief`, "/api/summarize-file"]);
  expect(fetch.mock.calls.map(([, init]) => (init.headers as Headers).get("Authorization"))).toEqual(["Bearer token-a", "Bearer token-b", null]);
  pending.reverse().forEach((resolve) => resolve());
  await Promise.all([a, b, local]);
});

it("surfaces shared transport errors without retrying writes", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response("fixture denied", { status: 403 }));
  vi.stubGlobal("fetch", fetch);
  await expect(briefApi.set(session, "text")).rejects.toMatchObject({ status: 403, message: "403: fixture denied" });
  expect(fetch).toHaveBeenCalledTimes(1);
});
