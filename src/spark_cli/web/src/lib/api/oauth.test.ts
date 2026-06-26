import { describe, expect, it } from "vitest";
import { createOAuthApi, type WithDashboardOrSessionToken } from "./oauth";
import type { FetchJSON } from "./model";

function recorder() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchJSON = (async <T>(url: string, init?: RequestInit): Promise<T> => {
    calls.push({ url, init });
    return {} as T;
  }) satisfies FetchJSON;
  const withAuth = ((run) =>
    run({ Authorization: "Bearer dashboard-token" })) satisfies WithDashboardOrSessionToken;
  return { api: createOAuthApi(fetchJSON, withAuth), calls };
}

describe("oauth api client", () => {
  it("keeps oauth read endpoints on their existing paths", async () => {
    const { api, calls } = recorder();

    await api.getOAuthProviders();
    await api.pollOAuthSession("codex provider", "session/id");

    expect(calls.map((call) => call.url)).toEqual([
      "/api/providers/oauth",
      "/api/providers/oauth/codex%20provider/poll/session%2Fid",
    ]);
  });

  it("preserves oauth authenticated mutation requests", async () => {
    const { api, calls } = recorder();

    await api.startOAuthLogin("codex");
    await api.submitOAuthCode("codex", "sid", "123456");
    await api.disconnectOAuthProvider("codex");
    await api.cancelOAuthSession("sid");

    expect(calls).toEqual([
      {
        url: "/api/providers/oauth/codex/start",
        init: {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer dashboard-token",
          },
          body: "{}",
        },
      },
      {
        url: "/api/providers/oauth/codex/submit",
        init: {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: "Bearer dashboard-token",
          },
          body: JSON.stringify({ session_id: "sid", code: "123456" }),
        },
      },
      {
        url: "/api/providers/oauth/codex",
        init: {
          method: "DELETE",
          headers: { Authorization: "Bearer dashboard-token" },
        },
      },
      {
        url: "/api/providers/oauth/sessions/sid",
        init: {
          method: "DELETE",
          headers: { Authorization: "Bearer dashboard-token" },
        },
      },
    ]);
  });
});
