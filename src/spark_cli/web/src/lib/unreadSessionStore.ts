/**
 * Module-level store for unread chat session notifications.
 *
 * Shared between ChatPage (writes/reads) and NotificationBell (reads).
 * Uses a simple pub/sub pattern — no React context needed.
 */

export interface SessionNotification {
  sessionId: string;
  title: string;
  preview: string | null;
  ts: number;
}

type Listener = () => void;

let notifications: SessionNotification[] = [];
const unreadIds = new Set<string>();
const listeners = new Set<Listener>();

function notify() {
  listeners.forEach((fn) => {
    try { fn(); } catch { /* ignore */ }
  });
}

/** Mark a session as having new (unread) content. */
export function addSessionNotification(
  sessionId: string,
  title: string,
  preview: string | null,
) {
  unreadIds.add(sessionId);
  const existing = notifications.findIndex((n) => n.sessionId === sessionId);
  const note: SessionNotification = { sessionId, title, preview, ts: Date.now() / 1000 };
  if (existing >= 0) {
    notifications = [
      note,
      ...notifications.filter((n) => n.sessionId !== sessionId),
    ];
  } else {
    notifications = [note, ...notifications].slice(0, 50);
  }
  notify();
}

/** Mark a session as read (user opened it). Keeps the notification entry but removes the unread dot. */
export function markSessionRead(sessionId: string) {
  if (unreadIds.has(sessionId)) {
    unreadIds.delete(sessionId);
    // Also remove from the notification list so the bell clears it too
    notifications = notifications.filter((n) => n.sessionId !== sessionId);
    notify();
  }
}

/** Explicitly dismiss a notification (e.g. from the bell dropdown). */
export function dismissSessionNotification(sessionId: string) {
  unreadIds.delete(sessionId);
  notifications = notifications.filter((n) => n.sessionId !== sessionId);
  notify();
}

/** Clear all session notifications. */
export function clearAllSessionNotifications() {
  unreadIds.clear();
  notifications = [];
  notify();
}

export function getUnreadSessionIds(): Set<string> {
  return new Set(unreadIds);
}

export function getSessionNotifications(): SessionNotification[] {
  return [...notifications];
}

export function getUnreadSessionCount(): number {
  return unreadIds.size;
}

/** Subscribe to store changes. Returns an unsubscribe function. */
export function subscribeToUnreadSessions(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
