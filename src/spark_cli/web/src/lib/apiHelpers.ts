/** Transport and URL helpers for the Spark web API.
 *
 * Split out of api.ts so the per-domain endpoint modules can use fetchJSON and
 * the auth helpers without importing api.ts, which imports them in turn.
 */

import {
  CONNECTION_MODE_KEY,
  REMOTE_BASE_URL_KEY,
  normalizeBaseUrl,
  parseConnectionMode,
  resolveApiBase,
  type ConnectionMode,
} from "./connection";


// Re-exported so existing api imports keep working unchanged.
export * from "./apiTypes";


const DASHBOARD_TOKEN_KEY = "spark_dashboard_token";

// ── Connection mode / API base URL ──────────────────────────────────────────
// In "local" mode the UI talks to the same origin it was served from (base "").
// In "remote" mode every request is prefixed with the stored remote base URL so
// the desktop app can drive an existing Spark instance (e.g. a VPS dashboard).
// getApiBase() is the SINGLE SOURCE OF TRUTH for the base URL — fetchJSON, the
// URL builders, and sseUrl all funnel through it.

export function getConnectionMode(): ConnectionMode {
  if (typeof localStorage === "undefined" || typeof localStorage.getItem !== "function") return "local";
  return parseConnectionMode(localStorage.getItem(CONNECTION_MODE_KEY));
}

export function getRemoteBaseUrl(): string | null {
  if (typeof localStorage === "undefined" || typeof localStorage.getItem !== "function") return null;
  return localStorage.getItem(REMOTE_BASE_URL_KEY);
}

/** Effective base URL prepended to every API/SSE/raw-file path ("" = same-origin). */
export function getApiBase(): string {
  return resolveApiBase(getConnectionMode(), getRemoteBaseUrl());
}

/**
 * Switch to a remote instance. Persists mode + normalized base URL and the
 * dashboard token together so they stay in sync. Caller is expected to have
 * already validated the connection (validateRemoteConnection in connection.ts).
 */
export function setRemoteConnection(baseUrl: string, token: string): void {
  localStorage.setItem(CONNECTION_MODE_KEY, "remote");
  localStorage.setItem(REMOTE_BASE_URL_KEY, normalizeBaseUrl(baseUrl) ?? baseUrl.trim().replace(/\/+$/, ""));
  setDashboardToken(token);
}

/** Switch back to the local sidecar: clears remote base + token. */
export function setLocalConnection(): void {
  localStorage.setItem(CONNECTION_MODE_KEY, "local");
  localStorage.removeItem(REMOTE_BASE_URL_KEY);
  clearDashboardToken();
}

// Ephemeral session token for protected endpoints (reveal).
// Fetched once on first reveal request and cached in memory.
let _sessionToken: string | null = null;

export function getDashboardToken(): string | null {
  if (typeof localStorage === "undefined" || typeof localStorage.getItem !== "function") return null;
  return localStorage.getItem(DASHBOARD_TOKEN_KEY);
}

export function setDashboardToken(token: string): void {
  localStorage.setItem(DASHBOARD_TOKEN_KEY, token.trim());
}

export function clearDashboardToken(): void {
  localStorage.removeItem(DASHBOARD_TOKEN_KEY);
}

/** Build a URL for raw-file serving (binary-safe) with auth token as query param.
 *  Use for <img src>, <video src>, and download <a href> where custom headers can't be sent. */
export function workspaceRawFileUrl(slug: string, path: string): string {
  const qs = new URLSearchParams({ path });
  const tok = getDashboardToken();
  if (tok) qs.set("dashboard_token", tok);
  return `${getApiBase()}/api/workspace/projects/${encodeURIComponent(slug)}/raw-file?${qs}`;
}

/** Build a protected URL for MEDIA:/absolute/path attachments in chat output. */
export function mediaFileUrl(path: string): string {
  const qs = new URLSearchParams({ path });
  const tok = getDashboardToken();
  if (tok) qs.set("dashboard_token", tok);
  return `${getApiBase()}/api/media?${qs}`;
}

/** Build a protected URL for downloading one of Spark's known log files. */
export function logsDownloadUrl(file: string): string {
  const qs = new URLSearchParams({ file });
  const tok = getDashboardToken();
  if (tok) qs.set("dashboard_token", tok);
  return `${getApiBase()}/api/logs/download?${qs}`;
}

/** Append dashboard auth for EventSource (no custom headers support). */
export function sseUrl(path: string): string {
  const full = `${getApiBase()}${path}`;
  const t = getDashboardToken();
  if (!t) return full;
  const sep = full.includes("?") ? "&" : "?";
  return `${full}${sep}dashboard_token=${encodeURIComponent(t)}`;
}

export function authHeaders(base?: HeadersInit): Headers {
  const h = new Headers(base);
  // Never clobber an Authorization header the caller set explicitly. The
  // OAuth/reveal endpoints authenticate with the per-process *session token*
  // (distinct from the dashboard token); overwriting it with the dashboard
  // token here made those endpoints 401 whenever a dashboard token was set.
  if (!h.has("Authorization")) {
    const tok = getDashboardToken();
    if (tok) h.set("Authorization", `Bearer ${tok}`);
  }
  return h;
}

export async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getApiBase()}${url}`, {
    ...init,
    headers: authHeaders(init?.headers),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    const err = new Error(`${res.status}: ${text}`) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}

async function getSessionToken(force = false): Promise<string> {
  if (_sessionToken && !force) return _sessionToken;
  const resp = await fetchJSON<{ token: string }>("/api/auth/session-token");
  _sessionToken = resp.token;
  return _sessionToken;
}

/**
 * Run a request that requires the per-process session token. The token is
 * regenerated whenever the backend restarts, so a cached value can go stale and
 * produce a 401. On a 401 we drop the cached token, refetch it, and retry once
 * before surfacing the error.
 */
export async function withSessionToken<T>(run: (token: string) => Promise<T>): Promise<T> {
  const token = await getSessionToken();
  try {
    return await run(token);
  } catch (e) {
    if (e instanceof Error && e.message.startsWith("401")) {
      _sessionToken = null;
      const fresh = await getSessionToken(true);
      return run(fresh);
    }
    throw e;
  }
}

export async function withDashboardOrSessionToken<T>(
  run: (headers: HeadersInit) => Promise<T>,
): Promise<T> {
  const dashboardToken = getDashboardToken();
  if (dashboardToken) {
    try {
      return await run({ Authorization: `Bearer ${dashboardToken}` });
    } catch (e) {
      if (!(e instanceof Error) || !e.message.startsWith("401")) {
        throw e;
      }
    }
  }
  return withSessionToken((token) => run({ Authorization: `Bearer ${token}` }));
}
