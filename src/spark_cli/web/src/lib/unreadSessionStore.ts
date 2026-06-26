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
  const existing = notifications.findIndex((n) => n.sessionId === sessionId);
  const note: SessionNotification = { sessionId, title, preview, ts: Date.now() / 1000 };
  if (
    existing >= 0 &&
    unreadIds.has(sessionId) &&
    notifications[existing].title === title &&
    notifications[existing].preview === preview
  ) {
    return;
  }
  unreadIds.add(sessionId);
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

/** Mark a session as read (user opened it). Removes any bell entry for that session. */
export function markSessionRead(sessionId: string) {
  const hadUnread = unreadIds.delete(sessionId);
  const beforeCount = notifications.length;
  // Also remove from the notification list so the bell clears it too
  notifications = notifications.filter((n) => n.sessionId !== sessionId);
  if (hadUnread || notifications.length !== beforeCount) {
    notify();
  }
}

/** Explicitly dismiss a notification (e.g. from the bell dropdown). */
export function dismissSessionNotification(sessionId: string) {
  const hadUnread = unreadIds.delete(sessionId);
  const beforeCount = notifications.length;
  notifications = notifications.filter((n) => n.sessionId !== sessionId);
  if (hadUnread || notifications.length !== beforeCount) notify();
}

/** Clear all session notifications. */
export function clearAllSessionNotifications() {
  if (unreadIds.size === 0 && notifications.length === 0) return;
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

export function resetUnreadSessionStoreForTests() {
  unreadIds.clear();
  notifications = [];
  listeners.clear();
}
