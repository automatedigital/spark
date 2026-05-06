import { useCallback, useEffect, useState } from "react";
import {
  Bot,
  Clock,
  Globe,
  Hash,
  Kanban,
  LayoutList,
  MessageCircle,
  MessageSquare,
  Plus,
  Search,
  Terminal,
  Trash2,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { SessionInfo, SessionSearchResult } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatPanel } from "@/components/ChatPanel";
import { useEventBus } from "@/hooks/useEventBus";
import { useI18n } from "@/i18n";

type KanbanStatus = "backlog" | "active" | "review" | "done";

const COLUMNS: { id: KanbanStatus; label: string; accent: string; bg: string }[] = [
  { id: "backlog", label: "Backlog", accent: "text-muted-foreground", bg: "bg-secondary/20" },
  { id: "active", label: "Active", accent: "text-primary", bg: "bg-primary/5" },
  { id: "review", label: "Review", accent: "text-warning", bg: "bg-warning/5" },
  { id: "done", label: "Done", accent: "text-success", bg: "bg-success/5" },
];

const SOURCE_ICONS: Record<string, typeof Terminal> = {
  cli: Terminal,
  telegram: MessageCircle,
  discord: Hash,
  slack: MessageSquare,
  whatsapp: Globe,
  web: Bot,
  cron: Clock,
};

function getKanbanStatus(session: SessionInfo): KanbanStatus {
  const status = session.kanban_status;
  if (status === "active" || status === "review" || status === "done") return status;
  return "backlog";
}

function SessionCard({
  session,
  onClick,
  onDragStart,
  onDragEnd,
  onDelete,
  onCreateTask,
}: {
  session: SessionInfo;
  onClick: () => void;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDelete: () => void;
  onCreateTask: () => void;
}) {
  const SourceIcon = SOURCE_ICONS[session.source ?? ""] ?? Globe;
  const hasTitle = session.title && session.title !== "Untitled";
  const modelShort = (session.model ?? "").split("/").pop() ?? "";
  const cost = session.estimated_cost_usd;
  const costStr =
    cost != null && cost > 0 ? (cost < 0.001 ? "<$0.001" : `$${cost.toFixed(3)}`) : null;

  return (
    <div
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onClick}
      className="group relative cursor-pointer rounded-md border border-border bg-background p-3 shadow-sm hover:border-primary/30 hover:shadow-md transition-all select-none"
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <span
          className={`text-xs truncate flex-1 ${hasTitle ? "font-medium" : "text-muted-foreground italic"}`}
        >
          {hasTitle ? session.title : session.preview ? session.preview.slice(0, 50) : "Untitled session"}
        </span>
        <div className="flex items-center gap-1 shrink-0">
          {session.is_active && (
            <span className="h-2 w-2 rounded-full bg-success animate-pulse mt-0.5" title="Active" />
          )}
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onCreateTask();
            }}
            className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-primary p-0.5 rounded"
            title="Create task from session"
          >
            <Plus className="h-3 w-3" />
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive p-0.5 rounded"
            title="Delete session"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </div>
      </div>

      <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground flex-wrap">
        <SourceIcon className="h-3 w-3 shrink-0" />
        {modelShort && <span className="truncate max-w-[90px]">{modelShort}</span>}
        <span className="text-border">·</span>
        <span>{session.message_count} msgs</span>
        {costStr && (
          <>
            <span className="text-border">·</span>
            <span className="text-success/80">{costStr}</span>
          </>
        )}
        <span className="text-border">·</span>
        <span>{timeAgo(session.last_active)}</span>
      </div>

      <div className="absolute inset-0 rounded-md ring-1 ring-primary/0 group-hover:ring-primary/20 transition-all pointer-events-none" />
    </div>
  );
}

export default function ConversationsPage() {
  const { t } = useI18n();
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [dragOverCol, setDragOverCol] = useState<KanbanStatus | null>(null);
  const [chatSessionId, setChatSessionId] = useState<string | null>(null);
  const [showNewChat, setShowNewChat] = useState(false);
  const [view, setView] = useState<"kanban" | "list">("kanban");
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<SessionSearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [taskNotice, setTaskNotice] = useState<string | null>(null);

  const loadSessions = useCallback(() => {
    api
      .getSessions(500, 0)
      .then((resp) => setSessions(resp.sessions))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  useEventBus((env) => {
    if (env.topic !== "sessions.changed") return;
    const data = env.data as { action?: string; session_id?: string; session?: SessionInfo };
    const action = data.action;
    const sid = data.session_id ?? "";
    const row = data.session;

    if (action === "deleted" && sid) {
      setSessions((prev) => prev.filter((s) => s.id !== sid));
      if (chatSessionId === sid) {
        setChatSessionId(null);
        setShowNewChat(false);
      }
      return;
    }

    if (row && sid) {
      setSessions((prev) => {
        const idx = prev.findIndex((s) => s.id === sid);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = { ...next[idx], ...row };
          return next;
        }
        return [row, ...prev];
      });
      return;
    }

    if (sid) loadSessions();
  });

  useEffect(() => {
    const q = searchQ.trim();
    if (!q) {
      setSearchResults(null);
      return;
    }
    const tmr = setTimeout(() => {
      setSearching(true);
      api
        .searchSessions(q, 40)
        .then((r) => setSearchResults(r.results))
        .catch(() => setSearchResults([]))
        .finally(() => setSearching(false));
    }, 280);
    return () => clearTimeout(tmr);
  }, [searchQ]);

  const columnSessions = (status: KanbanStatus) => sessions.filter((s) => getKanbanStatus(s) === status);

  const handleDrop = async (col: KanbanStatus) => {
    if (!draggingId || draggingId === col) return;
    setSessions((prev) => prev.map((s) => (s.id === draggingId ? { ...s, kanban_status: col } : s)));
    try {
      await api.patchSessionKanban(draggingId, col);
    } catch {
      loadSessions();
    }
    setDraggingId(null);
    setDragOverCol(null);
  };

  const handleDelete = async (sessionId: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== sessionId));
    if (chatSessionId === sessionId) closeChat();
    try {
      await api.deleteSession(sessionId);
    } catch {
      loadSessions();
    }
  };

  const openChat = (sessionId: string) => {
    setChatSessionId(sessionId);
    setShowNewChat(false);
  };

  const openNewChat = () => {
    setChatSessionId(null);
    setShowNewChat(true);
  };

  const closeChat = () => {
    setChatSessionId(null);
    setShowNewChat(false);
  };

  const handleSessionCreated = (id: string) => {
    setChatSessionId(id);
    setShowNewChat(false);
    loadSessions();
  };

  const createTaskForSession = async (session: SessionInfo) => {
    try {
      const title = session.title && session.title !== "Untitled" ? session.title : session.preview || session.id;
      await api.createKanbanTask({
        title: `Follow up: ${title}`.slice(0, 180),
        body: [
          `Source session: ${session.id}`,
          session.model ? `Model: ${session.model}` : "",
          session.source ? `Source: ${session.source}` : "",
          "",
          session.preview ?? "",
        ]
          .filter(Boolean)
          .join("\n"),
        board: "default",
        priority: 0,
      });
      setTaskNotice("Task created from conversation.");
      setTimeout(() => setTaskNotice(null), 2500);
    } catch (e) {
      setTaskNotice(e instanceof Error ? e.message : String(e));
    }
  };

  const chatOpen = chatSessionId !== null || showNewChat;

  const listRows = searchQ.trim() ? searchResults : null;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <div className={`flex flex-col gap-4 ${chatOpen ? "mr-[480px]" : ""} transition-[margin] duration-300`}>
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-base font-semibold">{t.app.nav.conversations}</h1>
          <Badge variant="secondary" className="text-xs">
            {sessions.length}
          </Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[200px] max-w-md">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              className="pl-8 h-9 text-sm"
              placeholder={t.common.search}
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
            />
            {searchQ && (
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setSearchQ("")}
                aria-label={t.common.clear}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <div className="flex rounded-md border border-border overflow-hidden">
            <Button
              type="button"
              variant={view === "kanban" ? "secondary" : "ghost"}
              size="sm"
              className="h-9 rounded-none gap-1"
              onClick={() => setView("kanban")}
            >
              <Kanban className="h-3.5 w-3.5" />
              Board
            </Button>
            <Button
              type="button"
              variant={view === "list" ? "secondary" : "ghost"}
              size="sm"
              className="h-9 rounded-none gap-1"
              onClick={() => setView("list")}
            >
              <LayoutList className="h-3.5 w-3.5" />
              List
            </Button>
          </div>
          <Button size="sm" className="h-9 gap-1.5" onClick={openNewChat}>
            <Plus className="h-3.5 w-3.5" />
            New conversation
          </Button>
        </div>
      </div>

      {searching && <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Searching…</p>}
      {taskNotice && <p className="text-xs border border-border p-2 text-muted-foreground">{taskNotice}</p>}

      {view === "kanban" ? (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {COLUMNS.map((col) => {
            const colSessions = columnSessions(col.id);
            const isOver = dragOverCol === col.id;
            return (
              <div
                key={col.id}
                className={`min-w-[240px] flex-1 flex flex-col rounded-lg border transition-colors ${
                  isOver ? "border-primary/40 bg-primary/5" : "border-border " + col.bg
                }`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragOverCol(col.id);
                }}
                onDragLeave={() => setDragOverCol(null)}
                onDrop={() => handleDrop(col.id)}
              >
                <div className="flex items-center gap-2 px-3 py-2.5 border-b border-border/50">
                  <span className={`text-xs font-semibold uppercase tracking-wider ${col.accent}`}>{col.label}</span>
                  <Badge variant="outline" className="text-[10px] h-4 px-1.5">
                    {colSessions.length}
                  </Badge>
                </div>
                <div className="flex flex-col gap-2 p-2 flex-1 min-h-[120px]">
                  {colSessions.length === 0 ? (
                    <div className="flex items-center justify-center flex-1 py-6">
                      <p className="text-[10px] text-muted-foreground/50 uppercase tracking-wider">Empty</p>
                    </div>
                  ) : (
                    colSessions.map((s) => (
                      <SessionCard
                        key={s.id}
                        session={s}
                        onClick={() => openChat(s.id)}
                        onDragStart={() => setDraggingId(s.id)}
                        onDragEnd={() => {
                          setDraggingId(null);
                          setDragOverCol(null);
                        }}
                        onDelete={() => handleDelete(s.id)}
                        onCreateTask={() => void createTaskForSession(s)}
                      />
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="flex flex-col gap-2 border border-border rounded-lg overflow-hidden">
          {listRows
            ? listRows.map((row) => {
                const sid = row.session_id;
                const sess = sessions.find((s) => s.id === sid);
                return (
                  <button
                    key={sid}
                    type="button"
                    className="flex items-center justify-between px-4 py-3 border-b border-border last:border-b-0 hover:bg-secondary/30 text-left transition-colors"
                    onClick={() => openChat(sid)}
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium truncate">
                        {sess?.title || sess?.preview || sid}
                      </p>
                      {row.snippet ? (
                        <p className="text-xs text-muted-foreground truncate mt-0.5">{row.snippet}</p>
                      ) : null}
                      <p className="text-[10px] text-muted-foreground mt-1">
                        {sess ? `${sess.message_count} msgs · ${timeAgo(sess.last_active)}` : sid}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleDelete(sid);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </button>
                );
              })
            : sessions.map((display) => (
                <button
                  key={display.id}
                  type="button"
                  className="flex items-center justify-between px-4 py-3 border-b border-border last:border-b-0 hover:bg-secondary/30 text-left transition-colors"
                  onClick={() => openChat(display.id)}
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium truncate">
                      {display.title || display.preview || display.id}
                    </p>
                    <p className="text-[10px] text-muted-foreground mt-1">
                      {display.message_count} msgs · {timeAgo(display.last_active)}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      void handleDelete(display.id);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </button>
              ))}
        </div>
      )}

      {sessions.length === 0 && !searchQ && (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <Clock className="h-8 w-8 mb-3 opacity-40" />
          <p className="text-sm font-medium">No sessions yet</p>
          <p className="text-xs mt-1 opacity-60">Start a conversation to see it here</p>
        </div>
      )}

      {chatOpen && (
        <ChatPanel sessionId={chatSessionId} onClose={closeChat} onSessionCreated={handleSessionCreated} />
      )}
    </div>
  );
}
