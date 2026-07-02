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

export interface StreamRenderSnapshotState {
  revision: number;
  textChars: number;
}

export interface StreamRenderSnapshot {
  text: string;
  revision?: number | null;
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

export function shouldApplyStreamRenderSnapshot(
  state: StreamRenderSnapshotState,
  snapshot: StreamRenderSnapshot,
): boolean {
  if (!snapshot.text) return false;
  const revision = typeof snapshot.revision === "number" ? snapshot.revision : null;
  if (revision !== null && revision > 0) {
    if (revision < state.revision) return false;
    if (revision === state.revision && snapshot.text.length <= state.textChars) return false;
    return true;
  }
  if (state.revision > 0 && revision !== null && revision < state.revision) return false;
  return snapshot.text.length > state.textChars;
}

export function applyStreamRenderSnapshotState(
  state: StreamRenderSnapshotState,
  snapshot: StreamRenderSnapshot,
): StreamRenderSnapshotState {
  const revision = typeof snapshot.revision === "number" ? snapshot.revision : 0;
  return {
    revision: Math.max(state.revision, revision),
    textChars: Math.max(state.textChars, snapshot.text.length),
  };
}
