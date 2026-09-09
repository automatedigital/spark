export type NotificationKind = "approval" | "question" | "failure" | "completion";
export interface NotificationPreferences {
  approvals: boolean; questions: boolean; failures: boolean; completions: boolean;
  quietStart: string; quietEnd: string; mutedProjects: string[];
}
export const DEFAULT_NOTIFICATION_PREFERENCES: NotificationPreferences = {
  approvals: true, questions: true, failures: true, completions: false,
  quietStart: "22:00", quietEnd: "07:00", mutedProjects: [],
};
const KEY = "spark-notification-preferences";
export function getNotificationPreferences(): NotificationPreferences {
  try { return { ...DEFAULT_NOTIFICATION_PREFERENCES, ...JSON.parse(localStorage.getItem(KEY) || "{}") }; } catch { return DEFAULT_NOTIFICATION_PREFERENCES; }
}
export function saveNotificationPreferences(value: NotificationPreferences): void { localStorage.setItem(KEY, JSON.stringify(value)); }
export function isQuietHours(now = new Date(), prefs = getNotificationPreferences()): boolean {
  if (!prefs.quietStart || !prefs.quietEnd || prefs.quietStart === prefs.quietEnd) return false;
  const minutes = now.getHours() * 60 + now.getMinutes();
  const [sh, sm] = prefs.quietStart.split(":").map(Number); const [eh, em] = prefs.quietEnd.split(":").map(Number);
  const start = sh * 60 + sm; const end = eh * 60 + em;
  return start < end ? minutes >= start && minutes < end : minutes >= start || minutes < end;
}
export function shouldNotify(kind: NotificationKind, projectSlug?: string | null, prefs = getNotificationPreferences(), now?: Date): boolean {
  if (projectSlug && prefs.mutedProjects.includes(projectSlug)) return false;
  if (isQuietHours(now, prefs)) return kind === "approval" || kind === "question";
  const key = ({ approval: "approvals", question: "questions", failure: "failures", completion: "completions" } as const)[kind];
  return prefs[key];
}
export function notificationIdentity(event: { id?: string; topic?: string; ts?: number; data?: { job_id?: string } }): string {
  return event.id || `${event.topic || "event"}:${event.data?.job_id || ""}:${event.ts || ""}`;
}
