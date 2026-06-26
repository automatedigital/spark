export interface StreamingRecoveryDecision {
  shouldResync: boolean;
  statusLabel: string | null;
}

export function streamingRecoveryDecision(
  elapsedSinceEventMs: number,
  elapsedSinceTokenMs: number,
  currentStatus: string | null,
): StreamingRecoveryDecision {
  let statusLabel: string | null = null;
  if (elapsedSinceEventMs >= 30_000) {
    statusLabel = "Reconnecting…";
  } else if (elapsedSinceEventMs >= 12_000) {
    statusLabel = "Still waiting for backend…";
  } else if (elapsedSinceTokenMs >= 12_000) {
    statusLabel = "Waiting for provider response…";
  } else if (elapsedSinceEventMs >= 3_000) {
    statusLabel = currentStatus ?? "Still working…";
  }
  return {
    shouldResync: elapsedSinceEventMs >= 3_000 || elapsedSinceTokenMs >= 12_000,
    statusLabel,
  };
}

export function shouldPollBackendActiveTurn(
  activeSessionId: string | null | undefined,
  streaming: boolean,
): activeSessionId is string {
  return Boolean(activeSessionId) && !streaming;
}
