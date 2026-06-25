export type ChatTurnState = "idle" | "starting" | "streaming" | "stalled" | "stopping" | "redirecting";

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
