import { resolveChatStatus, type ChatConnectionState } from "./chatStatus";

export interface RecoveryPollInput {
  streaming: boolean;
  hidden: boolean;
  now: number;
  lastEventAt: number;
  lastTokenAt: number;
  lastIdlePollAt: number;
  staleEventMs?: number;
  staleTokenMs?: number;
  idlePollMs?: number;
  /** Optional confirmed status used to reconcile the browser's optimistic hint. */
  backend?: {
    turnActive?: boolean | null;
    state?: string | null;
    phase?: string | null;
    status?: string | null;
    sessionActive?: boolean | null;
    connection?: ChatConnectionState | null;
  };
  optimisticLabel?: string | null;
  optimisticAt?: number | null;
}

export interface RecoveryPollDecision {
  poll: boolean;
  statusLabel?: string;
  statusKind?: ReturnType<typeof resolveChatStatus>["kind"];
  statusConfirmed?: boolean;
  optimisticExpired?: boolean;
  nextIdlePollAt: number;
}

export const RECOVERY_SIGNAL_COOLDOWN_MS = 2_000;
export const RECOVERY_SIGNAL_WINDOW_MS = 30_000;
export const RECOVERY_SIGNAL_MAX_PER_WINDOW = 3;

export interface RecoverySignalBudget {
  windowStartedAt: number;
  used: number;
  lastAllowedAt: number;
}

export function initialRecoverySignalBudget(): RecoverySignalBudget {
  return { windowStartedAt: 0, used: 0, lastAllowedAt: 0 };
}

export function consumeRecoverySignal(
  budget: RecoverySignalBudget,
  now: number,
): { allowed: boolean; budget: RecoverySignalBudget } {
  const freshWindow = budget.windowStartedAt === 0 || now - budget.windowStartedAt >= RECOVERY_SIGNAL_WINDOW_MS;
  const current = freshWindow
    ? { windowStartedAt: now, used: 0, lastAllowedAt: 0 }
    : budget;
  if (
    current.used >= RECOVERY_SIGNAL_MAX_PER_WINDOW ||
    (current.lastAllowedAt > 0 && now - current.lastAllowedAt < RECOVERY_SIGNAL_COOLDOWN_MS)
  ) {
    return { allowed: false, budget: current };
  }
  return {
    allowed: true,
    budget: { ...current, used: current.used + 1, lastAllowedAt: now },
  };
}

export function decideRecoveryPoll(input: RecoveryPollInput): RecoveryPollDecision {
  const {
    streaming,
    hidden,
    now,
    lastEventAt,
    lastTokenAt,
    lastIdlePollAt,
    staleEventMs = 3_000,
    staleTokenMs = 12_000,
    idlePollMs = 10_000,
  } = input;
  const elapsed = now - lastEventAt;
  const tokenElapsed = now - (lastTokenAt || lastEventAt);
  const confirmed = input.backend
    ? resolveChatStatus({
        turnActive: input.backend.turnActive,
        backendState: input.backend.state,
        backendPhase: input.backend.phase,
        backendLabel: input.backend.status,
        sessionActive: input.backend.sessionActive,
        connection: input.backend.connection,
        optimisticLabel: input.optimisticLabel,
        optimisticAt: input.optimisticAt,
        now,
      })
    : null;
  const reconciled = confirmed?.confirmed ? confirmed.label ?? undefined : undefined;
  const optimisticExpired = confirmed?.staleOptimistic ?? false;
  if (hidden) {
    if (!streaming) return { poll: false, statusLabel: reconciled, statusKind: confirmed?.kind, statusConfirmed: confirmed?.confirmed, optimisticExpired, nextIdlePollAt: lastIdlePollAt };
    return {
      poll: elapsed >= staleEventMs || tokenElapsed >= staleTokenMs,
      statusLabel: reconciled,
      statusKind: confirmed?.kind,
      statusConfirmed: confirmed?.confirmed,
      optimisticExpired,
      nextIdlePollAt: lastIdlePollAt,
    };
  }
  if (!streaming) {
    if (now - lastIdlePollAt >= idlePollMs) {
      return { poll: true, statusLabel: reconciled, statusKind: confirmed?.kind, statusConfirmed: confirmed?.confirmed, optimisticExpired, nextIdlePollAt: now };
    }
    return { poll: false, statusLabel: reconciled, statusKind: confirmed?.kind, statusConfirmed: confirmed?.confirmed, optimisticExpired, nextIdlePollAt: lastIdlePollAt };
  }
  return {
    poll: elapsed >= staleEventMs || tokenElapsed >= staleTokenMs,
    statusLabel: reconciled,
    statusKind: confirmed?.kind,
    statusConfirmed: confirmed?.confirmed,
    optimisticExpired,
    nextIdlePollAt: lastIdlePollAt,
  };
}
