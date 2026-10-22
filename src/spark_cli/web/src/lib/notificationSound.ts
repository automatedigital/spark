import { getNotificationPreferences, shouldPlayNotificationSound, type NotificationKind } from "./notificationPolicy";

export type SoundClass = "input" | "completion";
export type SoundResult = "played" | "blocked" | "suppressed";
export const SOUND_COOLDOWN_MS = 3000;

// One player per document, shared by chat, jobs and previews. No remote assets.
export function createNotificationSoundPlayer(createContext = () => new AudioContext(), clock = () => performance.now()) {
  let context: AudioContext | undefined;
  let lastAttempt = -Infinity;
  const seen = new Set<string>();

  async function play(sound: SoundClass): Promise<SoundResult> {
    const now = clock();
    if (now - lastAttempt < SOUND_COOLDOWN_MS) return "suppressed";
    lastAttempt = now; // Reserve before await: concurrent events cannot overlap.
    try {
      context ??= createContext();
      // Never queue an automatic sound behind browser autoplay permission.
      if (context.state !== "running") return "blocked";
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      const start = context.currentTime;
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(sound === "input" ? 880 : 660, start);
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.12, start + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.001, start + 0.22);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
      oscillator.start(start);
      oscillator.stop(start + 0.25);
      return "played";
    } catch {
      return "blocked";
    }
  }

  return {
    async preview(sound: SoundClass): Promise<SoundResult> {
      // Called only by the explicit Preview button, while a gesture is active.
      try {
        context ??= createContext();
        if (context.state !== "running") await context.resume();
        return await play(sound);
      } catch { return "blocked"; }
    },
    async notify(identity: string, kind: NotificationKind, projectSlug?: string | null): Promise<SoundResult> {
      if (seen.has(identity)) return "suppressed";
      seen.add(identity);
      if (seen.size > 512) seen.delete(seen.values().next().value!);
      if (!shouldPlayNotificationSound(kind, projectSlug, getNotificationPreferences())) return "suppressed";
      return play(kind === "completion" ? "completion" : "input");
    },
  };
}

export const notificationSound = createNotificationSoundPlayer();

/** Only semantic terminal / decision events may produce audio. */
export function soundKindForEvent(topic: string, data: Record<string, unknown>): NotificationKind | null {
  if (topic === "chat.approval_requested") return "approval";
  if (topic === "chat.input_requested") return "question";
  if (topic === "notifications.job_complete") return data.success === false ? null : "completion";
  if (topic === "chat.turn_done") {
    const outcome = data.turn_outcome as { status?: string } | null;
    return !data.interrupted && !data.backend_error_class && outcome?.status === "completed" ? "completion" : null;
  }
  return null;
}

export function soundEventIdentity(event: { topic: string; session_id?: string; data: Record<string, unknown> }, fallback: string): string {
  const value = (event.data.input ?? event.data.approval ?? event.data.turn_outcome) as { action_id?: string; id?: string; turn_id?: string } | undefined;
  const id = value?.action_id ?? value?.id ?? value?.turn_id;
  return id ? `${event.topic}:${event.session_id || ""}:${id}` : fallback;
}
