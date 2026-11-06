/** Versioned retry projection carried by the existing confirmed status seam. */
export const RETRY_STATUS_PREFIX = "spark.retry.v1:";
export interface RetryStatus {
  version: 1;
  reason_class: string;
  attempt: number;
  max_attempts: number;
  next_delay_seconds: number;
  next_attempt_at: number;
  observed_at: number;
  elapsed_seconds: number;
  budget_seconds: number;
  budget_deadline_at: number;
}
const reasons: Record<string, string> = {
  rate_limit: "Rate limit", overloaded: "Provider busy", server_error: "Provider error",
  auth: "Authentication failed", auth_permanent: "Authentication failed",
  billing: "Provider quota", model_not_found: "Model unavailable",
  context_overflow: "Context limit", payload_too_large: "Request too large",
  format_error: "Request rejected", thinking_signature: "Provider signature",
  long_context_tier: "Provider context limit",
  timeout: "Provider timeout", unknown: "Provider unavailable", invalid_response: "Invalid provider response",
};

/** Sparse server transitions need a fresh authoritative pill snapshot. */
export function shouldRefreshRetryStatus(topic: string, data: unknown, confirmedPhase?: string | null): boolean {
  const status = data && typeof data === "object" ? data as Record<string, unknown> : {};
  if (topic === "chat.status") {
    return confirmedPhase === "retry" || (status.kind === "retry" && typeof status.message === "string" && parseRetryStatus(status.message) !== null);
  }
  return confirmedPhase === "retry" && topic === "chat.token";
}

export function parseRetryStatus(label?: string | null): RetryStatus | null {
  if (!label?.startsWith(RETRY_STATUS_PREFIX)) return null;
  try {
    const data = JSON.parse(label.slice(RETRY_STATUS_PREFIX.length));
    if (data.version !== 1 || typeof data.reason_class !== "string" || !Object.hasOwn(reasons, data.reason_class)) return null;
    for (const field of ["attempt", "max_attempts", "next_delay_seconds", "next_attempt_at", "observed_at", "elapsed_seconds", "budget_seconds", "budget_deadline_at"]) {
      if (typeof data[field] !== "number" || !Number.isFinite(data[field]) || data[field] < 0) return null;
    }
    if (!Number.isInteger(data.attempt) || !Number.isInteger(data.max_attempts)
      || data.attempt < 1 || data.attempt > data.max_attempts
      || data.next_attempt_at > data.budget_deadline_at) return null;
    return data as RetryStatus;
  } catch { return null; }
}

export function retryStatusLabel(status: RetryStatus, now: number): string {
  if (now >= status.budget_deadline_at * 1000) return `${reasons[status.reason_class]} · waiting for backend status`;
  const seconds = Math.max(0, Math.ceil(status.next_attempt_at - now / 1000));
  return `${reasons[status.reason_class]} · retry ${status.attempt}/${status.max_attempts} · ${seconds > 0 ? `in ${seconds}s` : "awaiting provider"}`;
}

export function retryDisplayLabel(label: string | null | undefined, now: number): string | null {
  const retry = parseRetryStatus(label);
  if (retry) return retryStatusLabel(retry, now);
  return label?.startsWith(RETRY_STATUS_PREFIX) ? "Retry status unavailable" : label ?? null;
}
