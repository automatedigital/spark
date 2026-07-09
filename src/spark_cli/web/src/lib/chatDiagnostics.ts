import type { ChatTurnState } from "./chatTurnState";

export type RecoveryActionId = "reload" | "retry" | "stop" | "continue" | "copy";

export interface RecoveryAction {
  id: RecoveryActionId;
  label: string;
  enabled: boolean;
}

export interface RecoveryActionInput {
  hasSession: boolean;
  turnState: ChatTurnState;
  streaming: boolean;
  hasLastUserMessage: boolean;
  hasAssistantOutput: boolean;
  busy?: boolean;
}

export function recoveryActionsForTurn(input: RecoveryActionInput): RecoveryAction[] {
  const active = input.streaming || input.turnState !== "idle";
  const stale = input.turnState === "stalled";
  const stopping = input.turnState === "stopping" || input.turnState === "redirecting";
  const disabled = !input.hasSession || Boolean(input.busy);

  return [
    { id: "reload", label: "Reload transcript", enabled: !disabled },
    {
      id: "retry",
      label: "Retry last message",
      enabled: !disabled && !active && input.hasLastUserMessage,
    },
    {
      id: "stop",
      label: stopping ? "Stop requested" : "Stop turn",
      enabled: !disabled && active && !stopping,
    },
    {
      id: "continue",
      label: active ? "Redirect to continue" : "Continue",
      enabled: !disabled && (stale || !active) && input.hasAssistantOutput,
    },
    { id: "copy", label: "Copy diagnostics", enabled: !disabled },
  ];
}

const SECRET_KEY_RE = /(token|secret|password|api[_-]?key|authorization|cookie)/i;
const PATH_RE = /(?:\/Users\/|\/home\/|[A-Za-z]:\\)[^\s"',)]+/g;

function sanitizeValue(value: unknown, depth = 0): unknown {
  if (depth > 6) return "[Max depth]";
  if (typeof value === "string") {
    return value
      .replace(PATH_RE, "[local-path]")
      .slice(0, 2_000);
  }
  if (typeof value === "number" || typeof value === "boolean" || value == null) return value;
  if (Array.isArray(value)) return value.slice(0, 50).map((item) => sanitizeValue(item, depth + 1));
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      out[key] = SECRET_KEY_RE.test(key) ? "[Redacted]" : sanitizeValue(item, depth + 1);
    }
    return out;
  }
  return String(value);
}

export function safeDiagnosticsJson(value: unknown): string {
  return JSON.stringify(sanitizeValue(value), null, 2);
}

const COUNTERS_KEY = "__sparkChatDiagnosticCounters";

function counterStore(): Record<string, number> {
  const root = globalThis as typeof globalThis & { [COUNTERS_KEY]?: Record<string, number> };
  if (!root[COUNTERS_KEY]) root[COUNTERS_KEY] = {};
  return root[COUNTERS_KEY];
}

export function recordChatDiagnosticCounter(name: string, increment = 1): void {
  const counters = counterStore();
  counters[name] = (counters[name] ?? 0) + increment;
}

export function readChatDiagnosticCounters(): Record<string, number> {
  return { ...counterStore() };
}
