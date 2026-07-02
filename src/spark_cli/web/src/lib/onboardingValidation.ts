const PLACEHOLDER_SECRETS = new Set([
  "changeme",
  "change-me",
  "replace-me",
  "replace_me",
  "your-key",
  "your_key",
  "your-token",
  "your_token",
  "your-api-key",
  "placeholder",
  "example",
  "dummy",
  "null",
  "none",
]);

export interface ValidationResult {
  ok: boolean;
  value?: string;
  error?: string;
}

export function normalizeHttpBaseUrl(raw: string): string | null {
  const trimmed = (raw ?? "").trim();
  if (!trimmed || /\s/.test(trimmed)) return null;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  if (!parsed.hostname) return null;
  if (parsed.port) {
    const port = Number(parsed.port);
    if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
  }
  if (parsed.search || parsed.hash) return null;
  return (parsed.origin + parsed.pathname).replace(/\/+$/, "");
}

export function validateHttpBaseUrl(raw: string, label = "Base URL"): ValidationResult {
  const value = normalizeHttpBaseUrl(raw);
  if (!value) {
    return { ok: false, error: `${label} must be a valid HTTP(S) URL without spaces, query strings, or fragments.` };
  }
  return { ok: true, value };
}

export function normalizePort(raw: string): string | null {
  const trimmed = (raw ?? "").trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const port = Number(trimmed);
  if (!Number.isInteger(port) || port < 1 || port > 65535) return null;
  return String(port);
}

export function hasUsableSecret(raw: string, minLength = 4): boolean {
  const trimmed = (raw ?? "").trim();
  if (trimmed.length < minLength) return false;
  return !PLACEHOLDER_SECRETS.has(trimmed.toLowerCase());
}

export function validateSecret(raw: string, label = "Secret", minLength = 4): ValidationResult {
  const trimmed = (raw ?? "").trim();
  if (!hasUsableSecret(trimmed, minLength)) {
    return { ok: false, error: `${label} must be at least ${minLength} characters and not a placeholder.` };
  }
  return { ok: true, value: trimmed };
}

export function validateModelName(raw: string, label = "Model name"): ValidationResult {
  const trimmed = (raw ?? "").trim();
  if (!trimmed) return { ok: false, error: `${label} is required.` };
  if (trimmed.length > 200) return { ok: false, error: `${label} must be 200 characters or fewer.` };
  if (/\s|[\x00-\x1F]/.test(trimmed)) {
    return { ok: false, error: `${label} must not contain spaces or control characters.` };
  }
  return { ok: true, value: trimmed };
}
