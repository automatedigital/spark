// Pure, React-free connection-mode + remote-base-URL logic.
//
// Spark can run two ways from the desktop app:
//   - "local":  talk to the bundled sidecar on this computer (same-origin, base "").
//   - "remote": talk to an existing Spark instance (e.g. a VPS dashboard) by
//               prepending a configurable base URL to every API call and
//               authenticating with that instance's dashboard token.
//
// Everything in this module is intentionally pure and dependency-free so it can
// be unit-tested without a DOM or React. The localStorage glue lives in api.ts /
// the components; here we only own validation + normalization.

import { hasUsableSecret, normalizeHttpBaseUrl } from "./onboardingValidation";

export type ConnectionMode = "local" | "remote";

export const CONNECTION_MODE_KEY = "spark-connection-mode";
export const REMOTE_BASE_URL_KEY = "spark-remote-base-url";

/**
 * Normalize a user-supplied dashboard URL into a clean base URL with no
 * trailing slash. Returns null when the input is empty or not a valid
 * http(s) URL. Mirrors the `url.replace(/\/$/, "")` pattern used at the
 * App.tsx auth probe.
 */
export function normalizeBaseUrl(raw: string): string | null {
  return normalizeHttpBaseUrl(raw);
}

/** True when the string is a usable http(s) base URL. */
export function isValidBaseUrl(raw: string): boolean {
  return normalizeBaseUrl(raw) !== null;
}

/** A dashboard token is acceptable if it's a non-empty trimmed string. */
export function isValidToken(raw: string): boolean {
  return typeof raw === "string" && hasUsableSecret(raw);
}

/**
 * Build the URL to probe an instance's `/api/config` endpoint for validation.
 * `base` should already be normalized (no trailing slash) but we defend anyway.
 */
export function probeUrl(base: string): string {
  return `${base.replace(/\/+$/, "")}/api/config`;
}

/**
 * Resolve the effective API base for a given mode + remote URL. Returns "" for
 * same-origin (local mode, or remote with no/invalid URL), otherwise the
 * normalized remote base. This is the single source of truth used by
 * getApiBase() in api.ts.
 */
export function resolveApiBase(
  mode: ConnectionMode | null,
  remoteBaseUrl: string | null,
): string {
  if (mode !== "remote" || !remoteBaseUrl) return "";
  return normalizeBaseUrl(remoteBaseUrl) ?? "";
}

/** Coerce an arbitrary stored value into a valid ConnectionMode. */
export function parseConnectionMode(raw: string | null): ConnectionMode {
  return raw === "remote" ? "remote" : "local";
}

/** Extract a display host (e.g. "vps.example.com") from a base URL. */
export function displayHost(base: string | null): string {
  if (!base) return "";
  try {
    return new URL(base).host;
  } catch {
    return base;
  }
}

export interface ValidateResult {
  ok: boolean;
  status?: number;
  error?: string;
}

/**
 * Validate a remote connection by probing `${base}/api/config` with the given
 * token. Pure aside from the injectable fetch (defaults to global fetch), so it
 * is testable with a fake fetch.
 */
export async function validateRemoteConnection(
  rawUrl: string,
  rawToken: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ValidateResult> {
  const base = normalizeBaseUrl(rawUrl);
  if (!base) return { ok: false, error: "Invalid URL" };
  if (!isValidToken(rawToken)) return { ok: false, error: "Valid token required" };
  try {
    const res = await fetchImpl(probeUrl(base), {
      headers: { Authorization: `Bearer ${rawToken.trim()}` },
    });
    if (res.ok) return { ok: true, status: res.status };
    if (res.status === 401) {
      return { ok: false, status: 401, error: "Invalid token" };
    }
    return { ok: false, status: res.status, error: `HTTP ${res.status}` };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "Network error" };
  }
}
