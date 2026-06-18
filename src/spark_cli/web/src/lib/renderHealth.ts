export const SAFE_MODE_KEY_PREFIX = "spark-chat-safe-mode:";
export const RENDER_HEALTH_KEY = "spark-chat-render-health";

export interface RenderHealthSnapshot {
  session_id: string;
  safe_mode: boolean;
  long_task_count: number;
  updated_at: number;
}

export interface LongTaskSample {
  start: number;
  duration: number;
}

export function safeModeKey(sessionId: string): string {
  return `${SAFE_MODE_KEY_PREFIX}${sessionId}`;
}

export function readSafeMode(sessionId: string | null): boolean {
  if (!sessionId || typeof localStorage === "undefined") return false;
  return localStorage.getItem(safeModeKey(sessionId)) === "true";
}

export function persistSafeMode(sessionId: string | null, enabled: boolean): void {
  if (!sessionId || typeof localStorage === "undefined") return;
  if (enabled) localStorage.setItem(safeModeKey(sessionId), "true");
  else localStorage.removeItem(safeModeKey(sessionId));
}

export function rememberRenderHealth(sessionId: string | null, safeMode: boolean, longTaskCount = 0): void {
  if (!sessionId || typeof localStorage === "undefined") return;
  try {
    const snapshot: RenderHealthSnapshot = {
      session_id: sessionId,
      safe_mode: safeMode,
      long_task_count: longTaskCount,
      updated_at: Date.now(),
    };
    localStorage.setItem(RENDER_HEALTH_KEY, JSON.stringify(snapshot));
  } catch {
    /* ignore storage errors */
  }
}

export function pruneLongTasks(
  samples: LongTaskSample[],
  now: number,
  windowMs: number,
): LongTaskSample[] {
  const cutoff = now - windowMs;
  return samples.filter((sample) => sample.start >= cutoff);
}

export function shouldEnableSafeMode(
  samples: LongTaskSample[],
  options: {
    streaming: boolean;
    triggerCount: number;
    triggerDurationMs: number;
  },
): boolean {
  const maxDuration = samples.length ? Math.max(...samples.map((sample) => sample.duration)) : 0;
  return (options.streaming && samples.length >= options.triggerCount) || maxDuration >= options.triggerDurationMs;
}
