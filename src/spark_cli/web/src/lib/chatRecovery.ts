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
