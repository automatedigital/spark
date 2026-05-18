import { useEffect, useRef, useState } from "react";
import { Bell, CheckCircle, XCircle, X } from "lucide-react";
import { getDashboardToken } from "@/lib/api";

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
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);

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

  const handleOpen = () => {
    setOpen((o) => !o);
    if (!open) setUnread(0);
  };

  const dismiss = (id: string) =>
    setNotifications((prev) => prev.filter((n) => n.id !== id));

  return (
    <div className="relative" ref={panelRef}>
      <button
        type="button"
        aria-label="Notifications"
        onClick={handleOpen}
        className="relative grid h-8 w-8 place-items-center rounded-sm border border-transparent text-muted-foreground transition hover:border-border hover:bg-secondary hover:text-foreground"
      >
        <Bell className="h-4 w-4" />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 z-50 w-80 rounded-xl border border-border bg-popover shadow-2xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
            <span className="text-sm font-semibold">Notifications</span>
            {notifications.length > 0 && (
              <button
                type="button"
                className="text-[11px] text-muted-foreground hover:text-foreground transition"
                onClick={() => setNotifications([])}
              >
                Clear all
              </button>
            )}
          </div>
          <div className="max-h-[360px] overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="px-4 py-6 text-center text-sm text-muted-foreground">
                No notifications yet
              </div>
            ) : (
              notifications.map((n) => (
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
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
