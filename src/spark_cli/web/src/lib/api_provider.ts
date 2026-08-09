/** provider endpoints, split out of api.ts. */

import {
  fetchJSON,
  withDashboardOrSessionToken,
} from "./apiHelpers";
import type {
  OAuthProvidersResponse,
  OAuthStartResponse,
  OAuthSubmitResponse,
} from "./apiTypes";

export const providerApi = {
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
};
