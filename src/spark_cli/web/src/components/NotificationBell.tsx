import { useEffect, useRef, useState } from "react";
import { Bell, CheckCircle, MessageSquare, XCircle, X } from "lucide-react";
import { getDashboardToken } from "@/lib/api";
import { nativeNotify } from "@/lib/desktop";
import { setGlobalNavTarget } from "@/lib/globalNavigation";
import { isTauri } from "@/sidecar";
import {
  dismissSessionNotification,
  clearAllSessionNotifications,
  getSessionNotifications,
  getUnreadSessionCount,
  subscribeToUnreadSessions,
  type SessionNotification,
} from "@/lib/unreadSessionStore";

interface JobNotification {
  id: string;
  job_id: string;
  job_name: string;
  success: boolean;
  summary: string;
  ts: number;
}

const MAX_NOTIFICATIONS = 50;

export function NotificationBell() {
  const [notifications, setNotifications] = useState<JobNotification[]>([]);
  const [sessionNotifications, setSessionNotifications] = useState<SessionNotification[]>(getSessionNotifications);
  const [sessionUnread, setSessionUnread] = useState(getUnreadSessionCount);
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);

  // Subscribe to unread session store
  useEffect(() => subscribeToUnreadSessions(() => {
    setSessionNotifications(getSessionNotifications());
    setSessionUnread(getUnreadSessionCount());
  }), []);

  useEffect(() => {
    const token = getDashboardToken();
    const url = token
      ? `/api/events?topics=notifications&dashboard_token=${encodeURIComponent(token)}`
      : "/api/events?topics=notifications";
    const es = new EventSource(url);

    es.onmessage = (e) => {
      try {
        const env = JSON.parse(e.data);
        if (!env.topic?.startsWith("notifications.")) return;
        const d = env.data;
        const note: JobNotification = {
          id: `${env.ts}-${d.job_id}`,
          job_id: d.job_id,
          job_name: d.job_name,
          success: d.success,
          summary: d.summary,
          ts: env.ts,
        };
        setNotifications((prev) => [note, ...prev].slice(0, MAX_NOTIFICATIONS));
        setUnread((n) => n + 1);
        // Desktop (§3.2): surface a native OS notification so the user is
        // alerted even when the window is hidden / in the tray. No-ops on web.
        if (document.hidden || (isTauri() && !document.hasFocus())) {
          const title = note.success === false ? `⚠ ${note.job_name}` : note.job_name || "Spark";
          void nativeNotify(title, note.summary || "Background task completed.");
        }
      } catch {
        /* ignore malformed events */
      }
    };

    return () => es.close();
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const totalUnread = unread + sessionUnread;

  const handleOpen = () => {
    setOpen((o) => !o);
    if (!open) setUnread(0);
  };

  const dismiss = (id: string) =>
    setNotifications((prev) => prev.filter((n) => n.id !== id));

  const openSessionNotification = (sessionId: string) => {
    setGlobalNavTarget({ type: "thread", id: sessionId });
    dismissSessionNotification(sessionId);
    setOpen(false);
  };

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        aria-label="Notifications"
        onClick={handleOpen}
        className="relative grid h-8 w-8 place-items-center rounded-sm border border-transparent text-muted-foreground transition hover:border-border hover:bg-secondary hover:text-foreground"
      >
        <Bell className="h-4 w-4" />
        {totalUnread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
            {totalUnread > 9 ? "9+" : totalUnread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 z-50 w-80 rounded-xl border border-border bg-popover shadow-2xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <span className="text-sm font-semibold">Notifications</span>
            {(notifications.length > 0 || sessionNotifications.length > 0) && (
              <button
                type="button"
                className="text-[11px] text-muted-foreground hover:text-foreground transition"
                onClick={() => { setNotifications([]); clearAllSessionNotifications(); }}
              >
                Clear all
              </button>
            )}
          </div>
          <div className="max-h-[400px] overflow-y-auto">
            {notifications.length === 0 && sessionNotifications.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm text-muted-foreground">
                No notifications yet
              </div>
            ) : (
              <>
                {/* Chat session notifications */}
                {sessionNotifications.map((n) => (
                  <div
                    key={n.sessionId}
                    className="flex items-start gap-2 border-b border-border/50 px-4 py-3 transition-colors hover:bg-accent/30"
                  >
                    <button
                      type="button"
                      className="flex min-w-0 flex-1 items-start gap-3 text-left"
                      onClick={() => openSessionNotification(n.sessionId)}
                      aria-label={`Open ${n.title}`}
                    >
                      <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium">{n.title}</div>
                        {n.preview && (
                          <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                            {n.preview}
                          </div>
                        )}
                        <div className="mt-1 text-[10px] text-muted-foreground/60">
                          {new Date(n.ts * 1000).toLocaleTimeString()}
                        </div>
                      </div>
                    </button>
                    <button
                      type="button"
                      className="shrink-0 text-muted-foreground/50 transition hover:text-muted-foreground"
                      onClick={() => dismissSessionNotification(n.sessionId)}
                      aria-label="Dismiss"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
                {/* Cron job notifications */}
                {notifications.map((n) => (
                  <div
                    key={n.id}
                    className="flex items-start gap-3 px-4 py-3 border-b border-border/50 hover:bg-accent/30 transition-colors"
                  >
                    {n.success ? (
                      <CheckCircle className="h-4 w-4 shrink-0 text-success mt-0.5" />
                    ) : (
                      <XCircle className="h-4 w-4 shrink-0 text-destructive mt-0.5" />
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium truncate">{n.job_name}</div>
                      <div className="text-[11px] text-muted-foreground truncate mt-0.5">
                        {n.summary}
                      </div>
                      <div className="text-[10px] text-muted-foreground/60 mt-1">
                        {new Date(n.ts * 1000).toLocaleTimeString()}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="shrink-0 text-muted-foreground/50 hover:text-muted-foreground transition"
                      onClick={() => dismiss(n.id)}
                      aria-label="Dismiss"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
