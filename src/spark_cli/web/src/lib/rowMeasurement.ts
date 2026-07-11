/**
 * Pure helpers for chat-row virtualizer measurement.
 *
 * While a turn streams, only the live tail row (the assistant message still
 * receiving tokens) changes height constantly — measuring it per flush can
 * monopolize the main thread. Every other row, including committed assistant
 * rows, must keep being measured: positioning them from estimates is what
 * caused rows to overpaint each other during long streams.
 */

export interface MeasurableRowMsg {
  role: string;
  streaming?: boolean;
  content?: string;
}

export interface MeasurableRow {
  msg: MeasurableRowMsg | null;
}

/** Index of the live streaming assistant row, or -1 when no row is live. */
export function findLiveRowIndex(items: readonly MeasurableRow[]): number {
  for (let i = items.length - 1; i >= 0; i--) {
    const msg = items[i]?.msg;
    if (msg?.role === "assistant" && msg.streaming) return i;
  }
  return -1;
}

/**
 * Whether to skip `measureElement` for a row. Skips only:
 * - the single live streaming row (length-based estimate is good enough until
 *   the turn completes, when normal measurement resumes), and
 * - tool/reasoning rows under safe mode (measurement churn is what safe mode
 *   is protecting against).
 */
export function shouldSkipRowMeasurement(
  item: MeasurableRow | undefined,
  index: number,
  liveRowIndex: number,
  safeMode: boolean,
): boolean {
  const msg = item?.msg;
  if (!msg) return false;
  if (safeMode && (msg.role === "tool" || msg.role === "reasoning")) return true;
  return index === liveRowIndex;
}

/**
 * Height estimate for an assistant row. Uncapped (long answers routinely
 * exceed 900px) and code-fence aware: fenced blocks render taller per
 * character than prose (monospace lines, padding, header chrome).
 */
export function estimateAssistantRowSize(content: string, knownFenceCount?: number): number {
  const base = Math.ceil(content.length / 95) * 22 + 48;
  let fenceCount = knownFenceCount ?? 0;
  if (knownFenceCount === undefined) {
    for (let i = content.indexOf("```"); i !== -1; i = content.indexOf("```", i + 3)) {
      fenceCount += 1;
    }
  }
  const fencePairs = Math.floor(fenceCount / 2);
  return Math.min(20_000, Math.max(96, base + fencePairs * 120));
}
