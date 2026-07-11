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
}

export interface RecoveryPollDecision {
  poll: boolean;
  statusLabel?: string;
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
  if (hidden) {
    if (!streaming) return { poll: false, nextIdlePollAt: lastIdlePollAt };
    return {
      poll: elapsed >= staleEventMs || tokenElapsed >= staleTokenMs,
      nextIdlePollAt: lastIdlePollAt,
    };
  }
  if (!streaming) {
    if (now - lastIdlePollAt >= idlePollMs) {
      return { poll: true, nextIdlePollAt: now };
    }
    return { poll: false, nextIdlePollAt: lastIdlePollAt };
  }

  let statusLabel: string | undefined;
  if (elapsed >= 30_000) {
    statusLabel = "Reconnecting...";
  } else if (elapsed >= 12_000) {
    statusLabel = "Still waiting for backend...";
  }
  return {
    poll: elapsed >= staleEventMs || tokenElapsed >= staleTokenMs,
    statusLabel,
    nextIdlePollAt: lastIdlePollAt,
  };
}
