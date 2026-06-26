import type {
  OAuthPollResponse,
  OAuthProvidersResponse,
  OAuthStartResponse,
  OAuthSubmitResponse,
} from "../api";
import type { FetchJSON } from "./model";

export type WithDashboardOrSessionToken = <T>(
  run: (headers: HeadersInit) => Promise<T>,
) => Promise<T>;

export function createOAuthApi(
  fetchJSON: FetchJSON,
  withDashboardOrSessionToken: WithDashboardOrSessionToken,
) {
  return {
    getOAuthProviders: () =>
      fetchJSON<OAuthProvidersResponse>("/api/providers/oauth"),
    disconnectOAuthProvider: (providerId: string) =>
      withDashboardOrSessionToken((authHeader) =>
        fetchJSON<{ ok: boolean; provider: string }>(
          `/api/providers/oauth/${encodeURIComponent(providerId)}`,
          {
            method: "DELETE",
            headers: authHeader,
          },
        ),
      ),
    startOAuthLogin: (providerId: string) =>
      withDashboardOrSessionToken((authHeader) =>
        fetchJSON<OAuthStartResponse>(
          `/api/providers/oauth/${encodeURIComponent(providerId)}/start`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...authHeader,
            },
            body: "{}",
          },
        ),
      ),
    submitOAuthCode: (providerId: string, sessionId: string, code: string) =>
      withDashboardOrSessionToken((authHeader) =>
        fetchJSON<OAuthSubmitResponse>(
          `/api/providers/oauth/${encodeURIComponent(providerId)}/submit`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...authHeader,
            },
            body: JSON.stringify({ session_id: sessionId, code }),
          },
        ),
      ),
    pollOAuthSession: (providerId: string, sessionId: string) =>
      fetchJSON<OAuthPollResponse>(
        `/api/providers/oauth/${encodeURIComponent(providerId)}/poll/${encodeURIComponent(sessionId)}`,
      ),
    cancelOAuthSession: (sessionId: string) =>
      withDashboardOrSessionToken((authHeader) =>
        fetchJSON<{ ok: boolean }>(
          `/api/providers/oauth/sessions/${encodeURIComponent(sessionId)}`,
          {
            method: "DELETE",
            headers: authHeader,
          },
        ),
      ),
  };
}

export type OAuthApi = ReturnType<typeof createOAuthApi>;
