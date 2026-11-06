import { apiConnectionGeneration, fetchJSON } from "./apiHelpers";

export interface RoleTarget {
  provider: string;
  model: string;
  reasoning_effort: string;
  base_url: string;
  api_mode: string;
  fallback: string[];
  credential_presence: "present" | "not_detected" | "unknown";
  credential_required: boolean;
  availability: "unknown";
  capabilities: Record<string, "unknown">;
}
export interface RoutingSettings {
  schema_version: 1;
  selection: "auto" | "pinned";
  roles: Record<string, RoleTarget>;
  applies_to: "future_turn";
}
export interface RecordedRoute {
  turn_id: string;
  session_id: string;
  status: "recorded" | "unknown";
  model: string | null;
  role: string | null;
  provider: string | null;
  routing_reason: string | null;
  routing_decision: {
    role: string | null;
    desired_role: string | null;
    reason: string | null;
    signals: Record<string, string | number | boolean>;
    scores: Record<string, number>;
  } | null;
}
async function read<T>(path: string, signal?: AbortSignal): Promise<T> {
  const generation = apiConnectionGeneration();
  const result = await fetchJSON<T>(path, { signal, cache: "no-store" });
  if (generation !== apiConnectionGeneration()) throw new Error("Routing connection changed");
  return result;
}
export const getRoutingSettings = (signal?: AbortSignal) => read<RoutingSettings>("/api/model/routing", signal);
export const getRecordedRoutes = (sessionId: string, signal?: AbortSignal) =>
  read<{ schema_version: 1; turns: RecordedRoute[] }>(`/api/model/routing/turns/${encodeURIComponent(sessionId)}`, signal);

export const ROUTING_SETTINGS_SAVED_EVENT = "spark:routing-settings-saved";

/** Explain only the recorded reason; never classify the prompt again. */
export function describeRecordedRoute(turn: RecordedRoute): string {
  const reason = turn.routing_reason;
  if (turn.status === "unknown") return "Explanation unknown: this turn did not record a routing decision.";
  if (reason === "explicit_model_pinned") return "Your explicit model choice was used.";
  if (reason?.startsWith("auto_fallback:") && reason.endsWith("runtime_unavailable"))
    return "The selected role's runtime was unavailable; the primary route was used.";
  if (reason?.startsWith("auto_fallback:")) return "The role target was unavailable; the primary route was used.";
  if (reason?.endsWith(":high_risk_floor")) return "The recorded high-risk request required the lead role.";
  if (reason?.endsWith(":sticky_hysteresis")) return "The previous role was retained to avoid unnecessary switching.";
  if (reason?.startsWith("auto:") && reason.endsWith(":classified_signals"))
    return `Auto selected ${turn.role || turn.routing_decision?.role || "a role"} from the recorded request signals.`;
  if (reason === "adaptive_disabled") return "Adaptive routing was disabled for this turn.";
  return reason || turn.routing_decision?.reason || "Explanation unknown.";
}
