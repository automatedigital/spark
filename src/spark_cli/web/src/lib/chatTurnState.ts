export type ChatTurnState = "idle" | "starting" | "streaming" | "stalled" | "stopping" | "redirecting";
export type BackendTurnState =
  | "not_found"
  | "running"
  | "streaming"
  | "stalled"
  | "stopping"
  | "redirecting"
  | "complete"
  | "failed"
  | "interrupted"
  | string;

export type ChatTurnEvent =
  | { type: "submit" }
  | { type: "token" }
  | { type: "tool_start" }
  | { type: "tool_end" }
  | { type: "interrupt_requested"; redirect?: boolean }
  | { type: "turn_done" }
  | { type: "sse_reconnected"; backendActive: boolean; interruptRequested?: boolean; phase?: string | null }
  | { type: "session_migrated" };

export function normalizeBackendPhase(phase: string | null | undefined, interruptRequested = false): ChatTurnState {
  if (phase === "redirecting") return "redirecting";
  if (phase === "stopping") return "stopping";
  if (interruptRequested) return "stopping";
  if (phase === "starting") return "starting";
  if (phase === "stalled") return "stalled";
  if (phase && phase !== "idle") return "streaming";
  return "streaming";
}

export function recoverTurnStateFromBackend({
  turnActive,
  phase,
  state,
  interruptRequested = false,
}: {
  turnActive: boolean;
  phase?: string | null;
  state?: BackendTurnState | null;
  interruptRequested?: boolean;
}): ChatTurnState {
  if (!turnActive) return "idle";
  if (state === "stalled") return "stalled";
  if (state === "redirecting") return "redirecting";
  if (state === "stopping") return "stopping";
  if (state === "running" && phase === "starting") return "starting";
  if (state === "streaming") return "streaming";
  return normalizeBackendPhase(phase, interruptRequested);
}

export function backendTurnStatusLabel({
  turnActive,
  phase,
  state,
  status,
  idleForSeconds,
}: {
  turnActive: boolean;
  phase?: string | null;
  state?: BackendTurnState | null;
  status?: string | null;
  idleForSeconds?: number | null;
}): string | null {
  if (!turnActive) return null;
  if (state === "stalled") {
    const seconds = typeof idleForSeconds === "number" ? Math.floor(idleForSeconds) : null;
    return seconds !== null
      ? `Backend stalled for ${seconds}s`
      : "Backend stalled";
  }
  if (state === "stopping") return "Stopping response";
  if (state === "redirecting") return "Redirecting response";
  if (phase === "starting") return status || "Preparing agent";
  if (phase === "api") return status || "Waiting for provider response";
  if (phase === "tool") return status || "Tool running";
  if (phase === "reasoning") return status || "Reasoning";
  if (state === "streaming" || phase === "streaming") return status || "Streaming response";
  return status || "Working";
}

export function nextChatTurnState(current: ChatTurnState, event: ChatTurnEvent): ChatTurnState {
  switch (event.type) {
    case "submit":
      return "starting";
    case "token":
    case "tool_start":
    case "tool_end":
    case "session_migrated":
      return current === "stopping" || current === "redirecting" ? current : "streaming";
    case "interrupt_requested":
      return event.redirect ? "redirecting" : "stopping";
    case "turn_done":
      return "idle";
    case "sse_reconnected":
      if (!event.backendActive) return "idle";
      return normalizeBackendPhase(event.phase, event.interruptRequested);
    default:
      return current;
  }
}
