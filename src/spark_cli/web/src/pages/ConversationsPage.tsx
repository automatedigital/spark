import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot,
  Check,
  Edit3,
  Loader2,
  MessageSquare,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { SessionInfo, SessionSearchResult } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatPanel } from "@/components/ChatPanel";
import { useEventBus } from "@/hooks/useEventBus";

const WEB_SOURCE = "web";

function threadTitle(session: SessionInfo | null | undefined) {
  if (!session) return "New thread";
  const title = session.title?.trim();
  if (title && title !== "Untitled") return title;
  return session.preview?.trim() || "Untitled thread";
}

function modelShort(model: string | null | undefined) {
  return (model ?? "").split("/").pop() || "";
}

function sourceLabel(source: string | null | undefined) {
  const s = (source ?? "").toLowerCase();
  if (s === "cli") return "TUI";
  if (s === "web") return "Web";
  if (!s) return "Unknown";
  return s.replace(/(^|[_-])(\w)/g, (_, sep: string, chr: string) => `${sep ? " " : ""}${chr.toUpperCase()}`);
}

function optimisticThread(id: string, initialMessage?: string): SessionInfo {
  const now = Date.now() / 1000;
  return {
    id,
    source: WEB_SOURCE,
    model: null,
    title: null,
    started_at: now,
    ended_at: null,
    last_active: now,
    is_active: true,
    message_count: initialMessage ? 1 : 0,
    tool_call_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    preview: initialMessage?.trim() || null,
    kanban_status: null,
    estimated_cost_usd: null,
  };
}

function ThreadRow({
  session,
  active,
  searchSnippet,
  onOpen,
  onDelete,
}: {
  session: SessionInfo;
  active: boolean;
  searchSnippet?: string;
  onOpen: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={cn(
        "group relative flex w-full min-w-0 items-start gap-3 border-b border-border px-3 py-3 text-left transition",
        active ? "bg-primary/12" : "hover:bg-secondary/45",
      )}
    >
      <span
        className={cn(
          "mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-sm border",
          session.is_active
            ? "border-primary/45 bg-primary/18 text-primary"
            : "border-border bg-secondary/60 text-muted-foreground",
        )}
      >
        <MessageSquare className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-sm font-medium text-foreground">{threadTitle(session)}</span>
          {session.is_active && (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary shadow-[0_0_12px_rgba(255,163,43,0.8)]" />
          )}
        </span>
        <span className="mt-1 block truncate text-xs text-muted-foreground">
          {searchSnippet || session.preview || "No messages yet"}
        </span>
        <span className="mt-2 flex min-w-0 items-center gap-1.5 text-[10px] text-muted-foreground">
          {modelShort(session.model) && (
            <>
              <span className="truncate font-mono-ui max-w-[96px]">{modelShort(session.model)}</span>
              <span className="text-border">·</span>
            </>
          )}
          <span>{sourceLabel(session.source)}</span>
          <span className="text-border">·</span>
          <span>{session.message_count} msgs</span>
          <span className="text-border">·</span>
          <span>{timeAgo(session.last_active)}</span>
        </span>
      </span>
      <span
        className="absolute right-2 top-2 opacity-0 transition group-hover:opacity-100"
        onClick={(e) => e.stopPropagation()}
      >
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-destructive"
          title="Delete thread"
          onClick={onDelete}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </span>
    </div>
  );
}

export default function ConversationsPage() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newThread, setNewThread] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<SessionSearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  const loadThreads = useCallback(async () => {
    const resp = await api.getSessions(500, 0);
    setSessions(resp.sessions);
    return resp.sessions;
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadThreads()
      .then((rows) => {
        if (cancelled) return;
        if (rows.length > 0) setSelectedId(rows[0].id);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadThreads]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (!searchQ.trim()) void loadThreads();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [loadThreads, searchQ]);

  useEventBus((env) => {
    if (env.topic !== "sessions.changed") return;
    const data = env.data as { action?: string; session_id?: string; session?: SessionInfo };
    const sid = data.session_id ?? "";
    const row = data.session;

    if (data.action === "deleted" && sid) {
      setSessions((prev) => prev.filter((s) => s.id !== sid));
      if (selectedId === sid) {
        setSelectedId(null);
        setNewThread(false);
      }
      return;
    }

    if (row) {
      setSessions((prev) => {
        const idx = prev.findIndex((s) => s.id === row.id);
        if (idx >= 0) {
          const next = [...prev];
          const existing = next[idx];
          next[idx] = {
            ...existing,
            ...row,
            preview: row.preview?.trim() ? row.preview : existing.preview,
            message_count: Math.max(row.message_count ?? 0, existing.message_count ?? 0),
            is_active: typeof row.is_active === "boolean" ? row.is_active : existing.is_active,
          };
          return next.sort((a, b) => b.last_active - a.last_active);
        }
        return [row, ...prev];
      });
    }
  });

  useEffect(() => {
    const q = searchQ.trim();
    if (!q) {
      setSearchResults(null);
      return;
    }
    const t = setTimeout(() => {
      setSearching(true);
      api
        .searchSessions(q, 60)
        .then((r) => setSearchResults(r.results))
        .catch(() => setSearchResults([]))
        .finally(() => setSearching(false));
    }, 250);
    return () => clearTimeout(t);
  }, [searchQ]);

  const selectedSession = useMemo(
    () => sessions.find((s) => s.id === selectedId) ?? null,
    [selectedId, sessions],
  );

  const visibleThreads = useMemo(() => {
    if (!searchResults) return sessions.map((session) => ({ session, snippet: undefined as string | undefined }));
    const byId = new Map(sessions.map((s) => [s.id, s]));
    const rows: Array<{ session: SessionInfo; snippet?: string }> = [];
    searchResults.forEach((row) => {
      const session = byId.get(row.session_id);
      if (session) rows.push({ session, snippet: row.snippet });
    });
    return rows;
  }, [searchResults, sessions]);

  const openNewThread = () => {
    setSelectedId(null);
    setNewThread(true);
    setEditingTitle(false);
  };

  const openThread = (id: string) => {
    setSelectedId(id);
    setNewThread(false);
    setEditingTitle(false);
  };

  const handleSessionCreated = (id: string, initialMessage?: string) => {
    setSelectedId(id);
    setNewThread(false);
    setSessions((prev) => {
      const next = optimisticThread(id, initialMessage);
      const existing = prev.find((s) => s.id === id);
      if (!existing) return [next, ...prev];
      return [
        {
          ...existing,
          preview: existing.preview?.trim() ? existing.preview : next.preview,
          message_count: Math.max(existing.message_count ?? 0, next.message_count),
          is_active: true,
        },
        ...prev.filter((s) => s.id !== id),
      ];
    });
  };

  const handleDelete = async (id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (selectedId === id) {
      setSelectedId(null);
      setNewThread(false);
    }
    try {
      await api.deleteSession(id);
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
      void loadThreads();
    }
  };

  const beginRename = () => {
    if (!selectedSession) return;
    setTitleDraft(selectedSession.title || "");
    setEditingTitle(true);
  };

  const saveRename = async () => {
    if (!selectedSession) return;
    try {
      await api.renameSession(selectedSession.id, titleDraft);
      setEditingTitle(false);
      void loadThreads();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e));
    }
  };

  const chatVisible = newThread || !!selectedId;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="flex flex-1 min-h-0 overflow-hidden border-t border-border bg-card/75">
      <aside className={cn("flex min-h-0 w-full flex-col border-r border-border md:w-[360px]", chatVisible && "hidden md:flex")}>
        <div className="shrink-0 border-b border-border p-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-muted-foreground" />
                <h1 className="truncate text-sm font-semibold">Threads</h1>
                <Badge variant="secondary" className="h-5 text-[10px]">
                  {sessions.length}
                </Badge>
              </div>
              <p className="mt-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">All chats</p>
            </div>
            <Button size="sm" className="h-8 gap-1.5" onClick={openNewThread}>
              <Plus className="h-3.5 w-3.5" />
              New
            </Button>
          </div>
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              className="h-9 pl-8 pr-8 text-sm"
              placeholder="Search threads..."
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
            />
            {searchQ && (
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                onClick={() => setSearchQ("")}
                aria-label="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {searching && (
            <div className="flex items-center gap-2 border-b border-border px-3 py-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Searching
            </div>
          )}
          {visibleThreads.length > 0 ? (
            visibleThreads.map(({ session, snippet }) => (
              <ThreadRow
                key={session.id}
                session={session}
                searchSnippet={snippet}
                active={!newThread && selectedId === session.id}
                onOpen={() => openThread(session.id)}
                onDelete={() => void handleDelete(session.id)}
              />
            ))
          ) : (
            <div className="flex h-full flex-col items-center justify-center px-8 text-center text-muted-foreground">
              <Bot className="mb-3 h-9 w-9 opacity-35" />
              <p className="text-sm font-medium">{searchQ ? "No matching chats" : "No chats yet"}</p>
              <p className="mt-1 text-xs opacity-70">
                {searchQ ? "Try a different search." : "Start a new chat with Spark here."}
              </p>
            </div>
          )}
        </div>
      </aside>

      <section className={cn("min-w-0 flex-1 flex-col", chatVisible ? "flex" : "hidden md:flex")}>
        {chatVisible ? (
          <>
            {selectedSession && (
              <div className="hidden shrink-0 items-center justify-between gap-3 border-b border-border bg-background/70 px-4 py-2 md:flex">
                <div className="min-w-0 flex-1">
                  {editingTitle ? (
                    <div className="flex max-w-xl items-center gap-2">
                      <Input
                        className="h-8 text-sm"
                        value={titleDraft}
                        placeholder={selectedSession.preview || "Thread title"}
                        onChange={(e) => setTitleDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void saveRename();
                          if (e.key === "Escape") setEditingTitle(false);
                        }}
                        autoFocus
                      />
                      <Button size="icon" className="h-8 w-8" onClick={() => void saveRename()}>
                        <Check className="h-3.5 w-3.5" />
                      </Button>
                      <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setEditingTitle(false)}>
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex min-w-0 items-center gap-2">
                      <p className="truncate text-sm font-medium">{threadTitle(selectedSession)}</p>
                      <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground" onClick={beginRename}>
                        <Edit3 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            )}
            <ChatPanel
              sessionId={newThread ? null : selectedId}
              sessionTitle={selectedSession ? threadTitle(selectedSession) : null}
              onBack={() => {
                setNewThread(false);
                setSelectedId(null);
              }}
              onSessionCreated={handleSessionCreated}
              onSessionUpdated={() => void loadThreads()}
              className="min-h-0 flex-1"
            />
          </>
        ) : (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center text-muted-foreground">
            <MessageSquare className="mb-4 h-12 w-12 opacity-30" />
            <p className="text-sm font-medium text-foreground">Select a chat</p>
            <p className="mt-1 max-w-sm text-xs opacity-75">Open any previous Spark chat from the inbox or start a new one.</p>
            <Button className="mt-5 h-9 gap-1.5" onClick={openNewThread}>
              <Plus className="h-3.5 w-3.5" />
              New thread
            </Button>
          </div>
        )}
      </section>

      {notice && (
        <div className="fixed bottom-4 right-4 z-50 max-w-md rounded-sm border border-border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-xl">
          <button className="mr-2 text-muted-foreground hover:text-foreground" onClick={() => setNotice(null)}>
            <X className="inline h-3.5 w-3.5" />
          </button>
          {notice}
        </div>
      )}
    </div>
  );
}
