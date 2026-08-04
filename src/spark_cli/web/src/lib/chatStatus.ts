/**
 * The status shown beside the composer is deliberately resolved separately
 * from the optimistic stream reducer.  A reducer event tells us what the
 * browser last hoped was happening; a status/connection/session observation
 * tells us what Spark has actually confirmed.
 */

export type ChatConnectionState = "online" | "offline" | "reconnecting";

export type ChatStatusKind =
  | "idle"
  | "loading"
  | "working"
  | "streaming"
  | "stalled"
  | "stopping"
  | "redirecting"
  | "offline"
  | "reconnecting"
  | "interrupted"
  | "failed";

export type ChatStatusSource = "backend" | "session" | "connection" | "optimistic";

export interface ChatStatusInput {
  turnActive?: boolean | null;
  backendState?: string | null;
  backendPhase?: string | null;
  backendLabel?: string | null;
  sessionActive?: boolean | null;
  connection?: ChatConnectionState | null;
  optimisticLabel?: string | null;
  optimisticAt?: number | null;
  now?: number;
  optimisticTtlMs?: number;
}

export interface ResolvedChatStatus {
  kind: ChatStatusKind;
  label: string | null;
  source: ChatStatusSource;
  confirmed: boolean;
  staleOptimistic: boolean;
  expiresAt: number | null;
}

export const DEFAULT_OPTIMISTIC_TTL_MS = 12_000;

function nonEmpty(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function canonicalBackendStatus(input: ChatStatusInput): { kind: ChatStatusKind; label: string } | null {
  const state = input.backendState?.toLowerCase();
  const phase = input.backendPhase?.toLowerCase();
  const label = nonEmpty(input.backendLabel);

  if (state === "failed") return { kind: "failed", label: label ?? "Response failed" };
  if (state === "interrupted") return { kind: "interrupted", label: label ?? "Response interrupted" };
  if (state === "stalled") return { kind: "stalled", label: label ?? "Backend stalled" };
  if (state === "stopping" || phase === "stopping") return { kind: "stopping", label: label ?? "Stopping response" };
  if (state === "redirecting" || phase === "redirecting") {
    return { kind: "redirecting", label: label ?? "Redirecting response" };
  }
  if (phase === "starting") return { kind: "loading", label: label ?? "Preparing agent" };
  if (phase === "api") return { kind: "loading", label: label ?? "Waiting for provider response" };
  if (phase === "tool") return { kind: "working", label: label ?? "Tool running" };
  if (phase === "reasoning") return { kind: "working", label: label ?? "Reasoning" };
  if (state === "streaming" || phase === "streaming") {
    return { kind: "streaming", label: label ?? "Streaming response" };
  }
  if (state === "running" || (input.turnActive && state !== "complete" && state !== "not_found")) {
    return { kind: "working", label: label ?? "Working" };
  }
  return null;
}

function resolved(
  kind: ChatStatusKind,
  label: string | null,
  source: ChatStatusSource,
  confirmed: boolean,
  staleOptimistic = false,
  expiresAt: number | null = null,
): ResolvedChatStatus {
  return { kind, label, source, confirmed, staleOptimistic, expiresAt };
}

/**
 * Resolve display state with confirmed observations first.  `turnActive` is
 * intentionally not inferred from `optimisticLabel`; an optimistic submit
 * cannot keep a stale pill alive after the backend says the turn is over.
 */
export function resolveChatStatus(input: ChatStatusInput): ResolvedChatStatus {
  const now = input.now ?? Date.now();
  const ttl = input.optimisticTtlMs ?? DEFAULT_OPTIMISTIC_TTL_MS;

  if (input.connection === "offline") {
    return resolved("offline", "Offline — waiting to reconnect", "connection", true);
  }
  if (input.connection === "reconnecting") {
    return resolved("reconnecting", "Reconnecting to Spark", "connection", true);
  }

  const backend = canonicalBackendStatus(input);
  if (backend && (input.turnActive !== false || input.backendState === "failed" || input.backendState === "interrupted")) {
    return resolved(backend.kind, backend.label, "backend", true);
  }

  if (input.turnActive === false) {
    const optimisticExpired = Boolean(
      input.optimisticLabel
      && input.optimisticAt != null
      && now >= input.optimisticAt + ttl,
    );
    return resolved("idle", null, "backend", true, optimisticExpired, optimisticExpired ? input.optimisticAt! + ttl : null);
  }

  if (input.sessionActive === true) {
    return resolved("working", "Working", "session", true);
  }

  const optimisticLabel = nonEmpty(input.optimisticLabel);
  if (optimisticLabel) {
    const optimisticAt = input.optimisticAt ?? now;
    const expiresAt = optimisticAt + ttl;
    if (now < expiresAt) {
      return resolved("working", optimisticLabel, "optimistic", false, false, expiresAt);
    }
    return resolved("idle", null, "optimistic", false, true, expiresAt);
  }

  return resolved("idle", null, "backend", false);
}

/**
 * Keep this tiny helper available to components that already own a label but
 * have not yet migrated to the full status snapshot.
 */
export function reconcileOptimisticLabel({
  optimisticLabel,
  optimisticAt,
  confirmedLabel,
  now = Date.now(),
  ttlMs = DEFAULT_OPTIMISTIC_TTL_MS,
}: {
  optimisticLabel?: string | null;
  optimisticAt?: number | null;
  confirmedLabel?: string | null;
  now?: number;
  ttlMs?: number;
}): string | null {
  const confirmed = nonEmpty(confirmedLabel);
  if (confirmed) return confirmed;
  const optimistic = nonEmpty(optimisticLabel);
  if (!optimistic) return null;
  if (optimisticAt == null || now < optimisticAt + ttlMs) return optimistic;
  return null;
}
