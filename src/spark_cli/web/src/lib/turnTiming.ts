/** Server spans use only the server monotonic clock; no browser clock subtraction. */
export interface TurnTimingSummary {
  version: 1;
  clock: "server_monotonic";
  accepted: boolean;
  seconds: Partial<Record<"preparation" | "queue" | "provider_start" | "first_token" | "accepted_to_first_token" | "tools" | "finish", number | null>>;
  tool_count: number;
  usage: Partial<Record<"prompt_tokens" | "output_tokens" | "cache_read_tokens" | "cache_write_tokens" | "reasoning_tokens", number>> | null;
  provider?: string;
  model?: string;
  role?: string;
  routing_reason?: string;
  routing_decision?: { role?: string; desired_role?: string; reason?: string; signals?: Record<string, number | boolean>; scores?: Record<string, number> };
}

export function formatTurnDuration(value: number | null | undefined): string {
  return value != null && Number.isFinite(value) && value >= 0 ? `${value.toFixed(3)} s` : "Unknown";
}
