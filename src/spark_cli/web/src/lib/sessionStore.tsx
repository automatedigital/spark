/**
 * Shared session store — owns the projects/sessions lists, search, pinning,
 * selection and SSE updates that used to live inside ChatPage's sidebar.
 *
 * Mounted once in App.tsx; consumed by both the global sidebar and ChatPage.
 */
/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { api } from "@/lib/api";
import type { SessionInfo, WorkspaceProject } from "@/lib/api";
import {
  addSessionNotification,
  dismissSessionNotification,
  getUnreadSessionIds,
  markSessionRead,
  subscribeToUnreadSessions,
} from "@/lib/unreadSessionStore";
import { threadTitle } from "@/components/chat/ThreadRow";
import { useEventBus } from "@/hooks/useEventBus";
import type { SparkEventEnvelope } from "@/hooks/useEventBus";
import { GLOBAL_NAV_EVENT, takeGlobalNavTarget, type GlobalNavTarget } from "@/lib/globalNavigation";

const PINNED_KEY = "spark-pinned-sessions";
const EXPANDED_KEY = "spark-chat-expanded";

export function slugFromSource(source: string | null | undefined): string | null {
  if (!source?.startsWith("workspace:")) return null;
  return source.slice("workspace:".length);
}

function loadPinnedIds(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(PINNED_KEY) ?? "[]") as string[]);
  } catch {
    return new Set<string>();
  }
}

function loadExpanded(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(EXPANDED_KEY) ?? "[]") as string[]);
  } catch {
    return new Set<string>();
  }
}

export interface SessionStoreValue {
  // Data
  projects: WorkspaceProject[];
  sessions: SessionInfo[];
  loadingProjects: boolean;
  loadingSessions: boolean;

  // Search
  searchQ: string;
  setSearchQ: (q: string) => void;
  searchResults: SessionInfo[] | null;
  searching: boolean;
  /** Sessions to display in lists (search results when searching, else all). */
  displayedSessions: SessionInfo[];

  // Pinning
  pinnedIds: Set<string>;
  togglePin: (id: string) => void;

  // Selection / composing
  selectedId: string | null;
  selectedSession: SessionInfo | null;
  /** Workspace project slug being composed into, or null. */
  composingFor: string | null;
  selectSession: (id: string | null) => void;
  newSession: () => void;
  newProjectThread: (slug: string) => void;
  cancelCompose: () => void;
  /** First message of a just-created thread, consumed by ChatPanel. */
  pendingInitialMessage: string | null;
  clearPendingInitialMessage: () => void;
  threadCreated: (sessionId: string, initialMessage: string) => void;

  // Unread
  unreadSessionIds: Set<string>;

  // Project group expansion (sidebar)
  expandedProjects: Set<string>;
  toggleProjectExpanded: (slug: string) => void;

  // Actions
  deleteSession: (id: string) => Promise<void>;
  deleteProject: (slug: string) => Promise<void>;
  createProject: (name: string, template?: string) => Promise<string>;
  reloadSessions: () => Promise<void>;
  reloadProjects: () => Promise<void>;
}

const SessionStoreContext = createContext<SessionStoreValue | null>(null);

export function SessionStoreProvider({ children }: { children: React.ReactNode }) {
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [composingFor, setComposingFor] = useState<string | null>(null);
  const [pendingInitialMessage, setPendingInitialMessage] = useState<string | null>(null);

  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<SessionInfo[] | null>(null);
  const [searching, setSearching] = useState(false);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [pinnedIds, setPinnedIds] = useState<Set<string>>(loadPinnedIds);
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(loadExpanded);

  const [unreadSessionIds, setUnreadSessionIds] = useState<Set<string>>(getUnreadSessionIds);
  useEffect(() => subscribeToUnreadSessions(() => setUnreadSessionIds(getUnreadSessionIds())), []);

  // Track last-known message count per session so we can detect new messages via SSE
  const lastMessageCountRef = useRef<Map<string, number>>(new Map());
  const selectedIdRef = useRef<string | null>(null);
  selectedIdRef.current = selectedId;

  // ── Load data ──
  const reloadProjects = useCallback(async () => {
    setLoadingProjects(true);
    try {
      const res = await api.listWorkspaceProjects();
      setProjects(res.projects);
    } catch (e) {
      console.error("Load projects failed", e);
    } finally {
      setLoadingProjects(false);
    }
  }, []);

  const reloadSessions = useCallback(async () => {
    setLoadingSessions(true);
    try {
      const res = await api.getSessions(500, 0);
      // Seed known message counts — any SSE update that exceeds these is "new"
      const counts = new Map<string, number>();
      res.sessions.forEach((s) => counts.set(s.id, s.message_count ?? 0));
      lastMessageCountRef.current = counts;
      setSessions(res.sessions);
    } catch (e) {
      console.error("Load sessions failed", e);
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    void reloadProjects();
    void reloadSessions();
  }, [reloadProjects, reloadSessions]);

  // ── Real-time updates (SSE) ──
  useEventBus((env: SparkEventEnvelope) => {
    if (env.topic !== "sessions.changed") return;
    const data = env.data as { action?: string; session_id?: string; session?: SessionInfo };
    const sid = data.session_id ?? "";

    if (data.action === "deleted" && sid) {
      dismissSessionNotification(sid);
      setSessions((prev) => prev.filter((s) => s.id !== sid));
      if (selectedIdRef.current === sid) {
        setSelectedId(null);
        setComposingFor(null);
      }
      return;
    }

    if (data.session) {
      const row = data.session;

      // Detect new messages on a thread the user isn't currently viewing →
      // show an unread notification dot + bell entry.
      if (row.id !== selectedIdRef.current && (row.message_count ?? 0) > 0) {
        const lastCount = lastMessageCountRef.current.get(row.id) ?? 0;
        const newCount = row.message_count ?? 0;
        if (newCount > lastCount) {
          addSessionNotification(
            row.id,
            threadTitle(row) || "Untitled thread",
            row.preview ?? null,
          );
        }
        lastMessageCountRef.current.set(row.id, Math.max(lastCount, newCount));
      }

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

  // ── Search (debounced FTS with client-side fallback) ──
  useEffect(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    if (!searchQ.trim()) {
      setSearchResults(null);
      setSearching(false);
      return;
    }

    // Client-side filter for short queries
    if (searchQ.trim().length < 3) {
      const q = searchQ.toLowerCase();
      setSearchResults(sessions.filter(
        (s) => threadTitle(s).toLowerCase().includes(q) || s.preview?.toLowerCase().includes(q),
      ));
      return;
    }

    // FTS5 search for longer queries
    setSearching(true);
    searchDebounceRef.current = setTimeout(async () => {
      try {
        const res = await api.searchSessions(searchQ.trim(), 100);
        setSearchResults(
          res.results
            .map((r) => sessions.find((s) => s.id === r.session_id))
            .filter((s): s is SessionInfo => Boolean(s)),
        );
      } catch {
        // Fall back to client-side filter
        const q = searchQ.toLowerCase();
        setSearchResults(sessions.filter(
          (s) => threadTitle(s).toLowerCase().includes(q) || s.preview?.toLowerCase().includes(q),
        ));
      } finally {
        setSearching(false);
      }
    }, 300);
  }, [searchQ, sessions]);

  // ── Selection / composing ──
  const selectSession = useCallback((id: string | null) => {
    if (id) {
      markSessionRead(id);
      // Sync lastMessageCountRef to the latest known count so we don't
      // immediately re-fire a notification for messages we just acknowledged.
      setSessions((prev) => {
        const session = prev.find((s) => s.id === id);
        if (session?.message_count != null) {
          lastMessageCountRef.current.set(id, session.message_count);
        }
        return prev;
      });
    }
    setSelectedId(id);
    setComposingFor(null);
  }, []);

  const newSession = useCallback(() => {
    setSelectedId(null);
    setComposingFor(null);
    setSearchQ("");
  }, []);

  const toggleProjectExpanded = useCallback((slug: string) => {
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      localStorage.setItem(EXPANDED_KEY, JSON.stringify([...next]));
      return next;
    });
  }, []);

  const newProjectThread = useCallback((slug: string) => {
    setSelectedId(null);
    setComposingFor(slug);
    // Auto-expand the project folder
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      next.add(slug);
      localStorage.setItem(EXPANDED_KEY, JSON.stringify([...next]));
      return next;
    });
  }, []);

  const cancelCompose = useCallback(() => setComposingFor(null), []);

  const threadCreated = useCallback((sessionId: string, initialMessage: string) => {
    setPendingInitialMessage(initialMessage);
    setComposingFor(null);
    setSelectedId(sessionId);
    void reloadSessions();
  }, [reloadSessions]);

  const clearPendingInitialMessage = useCallback(() => setPendingInitialMessage(null), []);

  // Desktop tray "New Chat" + global sidebar "New session" dispatch this event.
  useEffect(() => {
    const handler = () => newSession();
    window.addEventListener("spark-new-chat", handler);
    return () => window.removeEventListener("spark-new-chat", handler);
  }, [newSession]);

  // ── Global nav targets (deep links + command palette) ──
  const openGlobalTarget = useCallback((target: GlobalNavTarget) => {
    if (target.type === "thread") {
      selectSession(target.id);
      setSearchQ("");
      return;
    }
    if (target.type === "project") {
      setSelectedId(null);
      setComposingFor(target.id);
      setSearchQ("");
      setExpandedProjects((prev) => {
        const next = new Set(prev);
        next.add(target.id);
        localStorage.setItem(EXPANDED_KEY, JSON.stringify([...next]));
        return next;
      });
    }
  }, [selectSession]);

  useEffect(() => {
    const projectTarget = takeGlobalNavTarget("project");
    const threadTarget = projectTarget ? null : takeGlobalNavTarget("thread");
    if (projectTarget) openGlobalTarget(projectTarget);
    if (threadTarget) openGlobalTarget(threadTarget);

    const handler = (event: Event) => {
      const target = (event as CustomEvent<GlobalNavTarget>).detail;
      if (target?.type === "project" || target?.type === "thread") openGlobalTarget(target);
    };
    window.addEventListener(GLOBAL_NAV_EVENT, handler);
    return () => window.removeEventListener(GLOBAL_NAV_EVENT, handler);
  }, [openGlobalTarget]);

  // ── Pinning ──
  const togglePin = useCallback((id: string) => {
    setPinnedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      localStorage.setItem(PINNED_KEY, JSON.stringify([...next]));
      return next;
    });
  }, []);

  // ── Mutations ──
  const deleteSession = useCallback(async (id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    setPinnedIds((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      localStorage.setItem(PINNED_KEY, JSON.stringify([...next]));
      return next;
    });
    if (selectedIdRef.current === id) setSelectedId(null);
    try {
      await api.deleteSession(id);
    } catch {
      void reloadSessions();
    }
  }, [reloadSessions]);

  const deleteProject = useCallback(async (slug: string) => {
    try {
      await api.deleteWorkspaceProject(slug);
      await reloadProjects();
      setComposingFor((prev) => (prev === slug ? null : prev));
      // Clear any selection that belonged to this project
      setSessions((prev) => {
        const selected = prev.find((s) => s.id === selectedIdRef.current);
        if (selected && slugFromSource(selected.source) === slug) setSelectedId(null);
        return prev;
      });
    } catch (e) {
      console.error("Delete project failed", e);
    }
  }, [reloadProjects]);

  const createProject = useCallback(async (name: string, template = "scratch"): Promise<string> => {
    const res = await api.createWorkspaceProject(name, template);
    await reloadProjects();
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      next.add(res.slug);
      localStorage.setItem(EXPANDED_KEY, JSON.stringify([...next]));
      return next;
    });
    return res.slug;
  }, [reloadProjects]);

  // ── Derived ──
  const displayedSessions = searchResults ?? sessions;
  const selectedSession = useMemo(
    () => sessions.find((s) => s.id === selectedId) ?? null,
    [sessions, selectedId],
  );

  const value: SessionStoreValue = {
    projects,
    sessions,
    loadingProjects,
    loadingSessions,
    searchQ,
    setSearchQ,
    searchResults,
    searching,
    displayedSessions,
    pinnedIds,
    togglePin,
    selectedId,
    selectedSession,
    composingFor,
    selectSession,
    newSession,
    newProjectThread,
    cancelCompose,
    pendingInitialMessage,
    clearPendingInitialMessage,
    threadCreated,
    unreadSessionIds,
    expandedProjects,
    toggleProjectExpanded,
    deleteSession,
    deleteProject,
    createProject,
    reloadSessions,
    reloadProjects,
  };

  return <SessionStoreContext.Provider value={value}>{children}</SessionStoreContext.Provider>;
}

export function useSessionStore(): SessionStoreValue {
  const ctx = useContext(SessionStoreContext);
  if (!ctx) throw new Error("useSessionStore must be used within SessionStoreProvider");
  return ctx;
}
