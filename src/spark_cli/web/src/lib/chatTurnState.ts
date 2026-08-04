import { resolveChatStatus, type ChatStatusInput, type ResolvedChatStatus } from "./chatStatus";

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
  const resolved = resolveConfirmedTurnStatus({
    turnActive,
    backendState: state,
    backendPhase: phase,
    backendLabel: status,
    idleForSeconds,
  });
  return resolved.label;
}

export interface ConfirmedTurnStatusInput extends ChatStatusInput {
  /** Backend API spelling retained as a convenience for direct status snapshots. */
  state?: BackendTurnState | null;
  idleForSeconds?: number | null;
}

/** Resolve a backend/session snapshot without treating a browser hint as truth. */
export function resolveConfirmedTurnStatus(input: ConfirmedTurnStatusInput): ResolvedChatStatus {
  const result = resolveChatStatus({ ...input, backendState: input.backendState ?? input.state });
  if (result.kind !== "stalled" || typeof input.idleForSeconds !== "number") return result;
  const seconds = Math.max(0, Math.floor(input.idleForSeconds));
  return {
    ...result,
    label: `Backend stalled for ${seconds}s`,
  };
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
