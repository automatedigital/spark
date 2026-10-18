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
import { DEFAULT_SIDEBAR_METADATA, SidebarMutationError, type SidebarAttention, type SidebarMetadata } from "./api_sidebar";
import { isEffectivelySettled, mergeSidebarEntries, sidebarMovePatches, type SidebarEntries } from "./sidebarOrganization";
import { readSidebarPreference, writeSidebarPreference, setSidebarPreferenceScope, sidebarPreferenceKey, SIDEBAR_SCOPE_EVENT } from "./sidebarPrefs";
import { api } from "@/lib/api";
import type {
  ProjectCreateRequest,
  SessionInfo,
  SessionSearchResult,
  WorkspaceProject,
} from "@/lib/api";
import {
  addSessionNotification,
  dismissSessionNotification,
  getUnreadSessionIds,
  markSessionRead,
  subscribeToUnreadSessions,
} from "@/lib/unreadSessionStore";
import { threadTitle } from "@/components/chat/ThreadRow";
import { STATE_SNAPSHOT_TOPIC, useEventBus } from "@/hooks/useEventBus";
import type { SparkEventEnvelope } from "@/hooks/useEventBus";
import { normalizedWebState, type WebStateSnapshotV1 } from "@/lib/webState";
import { GLOBAL_NAV_EVENT, takeGlobalNavTarget, type GlobalNavTarget } from "@/lib/globalNavigation";
import { recordChatDiagnosticCounter } from "@/lib/chatDiagnostics";

const PINNED_KEY = "spark-pinned-sessions";
const EXPANDED_KEY = "spark-chat-expanded";
const SELECTED_SESSION_KEY = "spark-selected-session-v1";
export const SESSION_PAGE_SIZE = 50;

export type PendingInitialMessages = Record<string, string>;

export interface ThreadCreatedMeta {
  source?: string | null;
  projectSlug?: string | null;
}

export function snapshotHasMoreSessions(snapshot: Pick<WebStateSnapshotV1, "shells" | "limits">): boolean {
  // A bounded snapshot does not carry a total. A full page is eligible for
  // paging; the ordinary page response proves exhaustion (including exact ties).
  return snapshot.limits.sessions > 0 && snapshot.shells.length >= snapshot.limits.sessions;
}

export function pendingInitialMessageForSession(
  pending: PendingInitialMessages,
  sessionId: string | null,
): string | undefined {
  return sessionId ? pending[sessionId] : undefined;
}

export function slugFromSource(source: string | null | undefined): string | null {
  if (!source?.startsWith("workspace:")) return null;
  return source.slice("workspace:".length);
}

export function mergeSessionRow(existing: SessionInfo | undefined, row: SessionInfo): SessionInfo {
  if (!existing) return row;
  return {
    ...existing,
    ...row,
    // Live session projections can be partial while a turn is starting.
    // Project-less sessions use the explicit "web" source, so null here
    // means "unknown" and must not erase a durable project assignment.
    source: row.source ?? existing.source,
    preview: row.preview?.trim() ? row.preview : existing.preview,
    message_count: Math.max(row.message_count ?? 0, existing.message_count ?? 0),
    is_active: typeof row.is_active === "boolean" ? row.is_active : existing.is_active,
  };
}

export function coalesceSessionRows(rows: SessionInfo[]): SessionInfo[] {
  const byId = new Map<string, SessionInfo>();
  rows.forEach((row) => {
    byId.set(row.id, mergeSessionRow(byId.get(row.id), row));
  });
  return [...byId.values()];
}

export function applySessionRows(prev: SessionInfo[], rows: SessionInfo[]): SessionInfo[] {
  if (rows.length === 0) return prev;
  let next = [...prev];
  coalesceSessionRows(rows).forEach((row) => {
    const idx = next.findIndex((s) => s.id === row.id);
    if (idx >= 0) {
      next[idx] = mergeSessionRow(next[idx], row);
    } else {
      next = [row, ...next];
    }
  });
  return next.sort((a, b) => b.last_active - a.last_active);
}

export function mergeSessionPage(prev: SessionInfo[], rows: SessionInfo[]): SessionInfo[] {
  return applySessionRows(prev, rows);
}

export function sessionInfoFromDetail(
  detail: Partial<SessionInfo> & { id: string },
  search?: SessionSearchResult,
): SessionInfo {
  const startedAt = detail.started_at ?? search?.session_started ?? 0;
  return {
    id: detail.id,
    source: detail.source ?? search?.source ?? null,
    model: detail.model ?? search?.model ?? null,
    title: detail.title ?? search?.title ?? null,
    started_at: startedAt,
    ended_at: detail.ended_at ?? null,
    last_active: detail.last_active ?? startedAt,
    is_active: detail.is_active ?? false,
    message_count: detail.message_count ?? 0,
    tool_call_count: detail.tool_call_count ?? 0,
    input_tokens: detail.input_tokens ?? 0,
    output_tokens: detail.output_tokens ?? 0,
    preview: detail.preview ?? search?.snippet ?? null,
    kanban_status: detail.kanban_status ?? null,
    estimated_cost_usd: detail.estimated_cost_usd ?? null,
  };
}

export function filterSessionsLocally(sessions: SessionInfo[], query: string): SessionInfo[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return sessions;
  return sessions.filter(
    (session) => threadTitle(session).toLowerCase().includes(normalized)
      || session.preview?.toLowerCase().includes(normalized),
  );
}

export function mergeSearchRows(primary: SessionInfo[], secondary: SessionInfo[]): SessionInfo[] {
  const seen = new Set(primary.map((session) => session.id));
  return [
    ...primary,
    ...secondary.filter((session) => {
      if (seen.has(session.id)) return false;
      seen.add(session.id);
      return true;
    }),
  ];
}

function loadExpanded(): Set<string> {
  try {
    return new Set(JSON.parse(readSidebarPreference(EXPANDED_KEY) ?? "[]") as string[]);
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
  loadingMoreSessions: boolean;
  hasMoreSessions: boolean;
  sessionsError: string | null;

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

  sidebarMetadata: SidebarEntries;
  sidebarAttention: Record<string, SidebarAttention>;
  sidebarMetadataError: string | null;
  sidebarMetadataReady: boolean;
  sidebarBusy: boolean;
  sidebarUndo: { id: string; settled: boolean; revision: number } | null;
  toggleSettled: (id: string) => void;
  undoSidebarChange: () => void;
  moveSidebarSession: (id: string, direction: -1 | 1) => void;
  reloadSidebarMetadata: () => Promise<void>;
  importLocalPins: () => void;
  canImportLocalPins: boolean;

  // Selection / composing
  selectedId: string | null;
  selectedSession: SessionInfo | null;
  /** Workspace project slug being composed into, or null. */
  composingFor: string | null;
  /** Project filter selected in the inbox sidebar; seeds the new-chat composer. */
  sidebarProjectScope: string | null;
  setSidebarProjectScope: (slug: string | null) => void;
  selectSession: (id: string | null) => void;
  newSession: () => void;
  newProjectThread: (slug: string) => void;
  cancelCompose: () => void;
  /** First message of a just-created thread, consumed by ChatPanel. */
  pendingInitialMessages: PendingInitialMessages;
  clearPendingInitialMessage: (sessionId?: string) => void;
  threadCreated: (sessionId: string, initialMessage: string, meta?: ThreadCreatedMeta) => void;

  // Unread
  unreadSessionIds: Set<string>;

  // Project group expansion (sidebar)
  expandedProjects: Set<string>;
  toggleProjectExpanded: (slug: string) => void;

  // Actions
  deleteSession: (id: string) => Promise<void>;
  deleteProject: (slug: string) => Promise<void>;
  createProject: (request: ProjectCreateRequest | string, template?: string) => Promise<string>;
  moveSessionToProject: (id: string, slug: string | null) => Promise<void>;
  renameProject: (slug: string, name: string) => Promise<string>;
  reloadSessions: () => Promise<void>;
  loadMoreSessions: () => Promise<void>;
  reloadProjects: (requiredSlug?: string) => Promise<boolean>;
}

const SessionStoreContext = createContext<SessionStoreValue | null>(null);

export function SessionStoreProvider({ children }: { children: React.ReactNode }) {
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const sessionsRef = useRef<SessionInfo[]>([]);
  sessionsRef.current = sessions;
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(false);
  const [loadingMoreSessions, setLoadingMoreSessions] = useState(false);
  const [hasMoreSessions, setHasMoreSessions] = useState(false);
  const [sessionsError, setSessionsError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(() => {
    try { return readSidebarPreference(SELECTED_SESSION_KEY); } catch { return null; }
  });
  const [composingFor, setComposingFor] = useState<string | null>(null);
  const [sidebarProjectScope, setSidebarProjectScope] = useState<string | null>(null);
  const [pendingInitialMessages, setPendingInitialMessages] = useState<PendingInitialMessages>({});

  const [searchQ, setSearchQuery] = useState("");
  const searchQueryRef = useRef("");
  const [searchResults, setSearchResults] = useState<SessionInfo[] | null>(null);
  const [searching, setSearching] = useState(false);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchRequestRef = useRef(0);
  const setSearchQ = useCallback((query: string) => {
    if (query === searchQueryRef.current) return;
    searchQueryRef.current = query;
    // Commit the input and loaded-page results together, without an effect's
    // second render. Invalidate old FTS responses before the next effect runs.
    searchRequestRef.current += 1;
    setSearchQuery(query);
    setSearchResults(query.trim() ? filterSessionsLocally(sessionsRef.current, query) : null);
    setSearching(Boolean(query.trim()));
  }, []);
  const queuedSessionRowsRef = useRef<Map<string, SessionInfo>>(new Map());
  const queuedSessionRowsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const nextSessionsOffsetRef = useRef(0);
  const loadingMoreRef = useRef(false);
  const hydrationRequestsRef = useRef<Map<string, Promise<SessionInfo | null>>>(new Map());

  const [sidebarMetadata, setSidebarMetadata] = useState<SidebarEntries>({});
  const metadataRef = useRef(sidebarMetadata);
  metadataRef.current = sidebarMetadata;
  const [sidebarAttention, setSidebarAttention] = useState<Record<string, SidebarAttention>>({});
  const [sidebarMetadataError, setSidebarMetadataError] = useState<string | null>(null);
  const sidebarMutationErrorRef = useRef<string | null>(null);
  const [sidebarMetadataReady, setSidebarMetadataReady] = useState(false);
  const [sidebarBusy, setSidebarBusy] = useState(false);
  const busyRef = useRef(false);
  const [sidebarUndo, setSidebarUndo] = useState<{ id: string; settled: boolean; revision: number } | null>(null);
  const [canImportLocalPins, setCanImportLocalPins] = useState(false);
  const pinnedIds = useMemo(() => new Set(Object.keys(sidebarMetadata).filter((id) => sidebarMetadata[id].pinned)), [sidebarMetadata]);
  const pinnedIdsRef = useRef(pinnedIds);
  pinnedIdsRef.current = pinnedIds;
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(loadExpanded);

  const [unreadSessionIds, setUnreadSessionIds] = useState<Set<string>>(getUnreadSessionIds);
  useEffect(() => subscribeToUnreadSessions(() => setUnreadSessionIds(getUnreadSessionIds())), []);

  // Track last-known message count per session so we can detect new messages via SSE
  const lastMessageCountRef = useRef<Map<string, number>>(new Map());
  const notifiedMessageCountRef = useRef<Map<string, number>>(new Map());
  const selectedIdRef = useRef<string | null>(null);
  selectedIdRef.current = selectedId;

  // ── Load data ──
  const projectRequestRef = useRef(0);
  const reloadProjects = useCallback(async (requiredSlug?: string) => {
    const request = ++projectRequestRef.current;
    const scope = sidebarPreferenceKey("project-list");
    setLoadingProjects(true);
    try {
      const res = await api.listWorkspaceProjects();
      if (request !== projectRequestRef.current || scope !== sidebarPreferenceKey("project-list")) return false;
      setProjects(res.projects);
      return !requiredSlug || res.projects.some((project) => project.slug === requiredSlug);
    } catch (e) {
      console.error("Load projects failed", e);
      return false;
    } finally {
      if (request === projectRequestRef.current) setLoadingProjects(false);
    }
  }, []);

  const reloadSessions = useCallback(async () => {
    setLoadingSessions(true);
    setSessionsError(null);
    recordChatDiagnosticCounter("sidebar_reload_sessions");
    try {
      const res = await api.getSessions(SESSION_PAGE_SIZE, 0);
      // Seed known message counts — any SSE update that exceeds these is "new"
      // without forgetting older pages already loaded into this store.
      const counts = new Map(lastMessageCountRef.current);
      const notifiedCounts = new Map(notifiedMessageCountRef.current);
      res.sessions.forEach((s) => {
        counts.set(s.id, s.message_count ?? 0);
        notifiedCounts.set(s.id, Math.max(notifiedCounts.get(s.id) ?? 0, s.message_count ?? 0));
      });
      lastMessageCountRef.current = counts;
      notifiedMessageCountRef.current = notifiedCounts;
      nextSessionsOffsetRef.current = Math.max(nextSessionsOffsetRef.current, res.sessions.length);
      setHasMoreSessions(nextSessionsOffsetRef.current < res.total);
      setSessions((prev) => (prev.length === 0 ? coalesceSessionRows(res.sessions) : mergeSessionPage(prev, res.sessions)));
    } catch (e) {
      console.error("Load sessions failed", e);
      setSessionsError(e instanceof Error ? e.message : "Could not load sessions");
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  const loadMoreSessions = useCallback(async () => {
    if (
      loadingMoreRef.current
      || (!hasMoreSessions && nextSessionsOffsetRef.current > 0)
    ) return;
    loadingMoreRef.current = true;
    setLoadingMoreSessions(true);
    setSessionsError(null);
    const offset = nextSessionsOffsetRef.current;
    try {
      const res = await api.getSessions(SESSION_PAGE_SIZE, offset);
      nextSessionsOffsetRef.current = offset + res.sessions.length;
      setSessions((prev) => mergeSessionPage(prev, res.sessions));
      setHasMoreSessions(res.sessions.length > 0 && nextSessionsOffsetRef.current < res.total);
    } catch (e) {
      console.error("Load older sessions failed", e);
      setSessionsError(e instanceof Error ? e.message : "Could not load older sessions");
    } finally {
      loadingMoreRef.current = false;
      setLoadingMoreSessions(false);
    }
  }, [hasMoreSessions]);

  const hydrateSession = useCallback((id: string, search?: SessionSearchResult): Promise<SessionInfo | null> => {
    const existing = hydrationRequestsRef.current.get(id);
    if (existing) return existing;
    const request = api.getSession(id)
      .then((detail) => {
        const row = sessionInfoFromDetail(detail, search);
        setSessions((prev) => mergeSessionPage(prev, [row]));
        return row;
      })
      .catch((error) => {
        console.error(`Load session ${id} failed`, error);
        return null;
      })
      .finally(() => hydrationRequestsRef.current.delete(id));
    hydrationRequestsRef.current.set(id, request);
    return request;
  }, []);

  const metadataRequestRef = useRef(0);
  const metadataScopeRef = useRef<string | null>(null);
  const reloadSidebarMetadata = useCallback(async () => {
    const request = ++metadataRequestRef.current;
    try {
      const snapshot = await api.getSidebarThreads();
      if (request !== metadataRequestRef.current) return;
      if (snapshot.schema_version !== 1) throw new Error("Unsupported sidebar metadata version");
      const scopeChanged = metadataScopeRef.current !== snapshot.preference_scope;
      metadataScopeRef.current = snapshot.preference_scope;
      setSidebarPreferenceScope(snapshot.preference_scope);
      if (scopeChanged) {
        setExpandedProjects(loadExpanded());
        setSelectedId((current) => current ?? (readSidebarPreference(SELECTED_SESSION_KEY) || null));
        setSidebarUndo(null);
      }
      setSidebarMetadata((current) => scopeChanged ? snapshot.entries : mergeSidebarEntries(current, snapshot.entries));
      setSidebarAttention(snapshot.attention ?? {});
      setSidebarMetadataReady(true);
      setSidebarMetadataError(sidebarMutationErrorRef.current);
      try {
        const legacy = JSON.parse(localStorage.getItem(PINNED_KEY) ?? "[]");
        setCanImportLocalPins(!readSidebarPreference("spark-sidebar-pin-import") && Array.isArray(legacy) && legacy.some((id: unknown) => typeof id === "string" && snapshot.entries[id]?.revision === 0));
      } catch { setCanImportLocalPins(false); }
    } catch (error) {
      if (request === metadataRequestRef.current) {
        setSidebarMetadataReady(false);
        setSidebarMetadataError(error instanceof Error ? error.message : "Could not load thread organization");
      }
    }
  }, []);
  useEffect(() => {
    void reloadSidebarMetadata();
    const refresh = () => { if (document.visibilityState !== "hidden") void reloadSidebarMetadata(); };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    // One bounded subscription for all rows, also covering other backend processes.
    const timer = window.setInterval(refresh, 15000);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", refresh); document.removeEventListener("visibilitychange", refresh); };
  }, [reloadSidebarMetadata]);

  const metadataRefreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queueSidebarMetadataReload = useCallback(() => {
    if (metadataRefreshTimer.current) return;
    metadataRefreshTimer.current = setTimeout(() => {
      metadataRefreshTimer.current = null;
      void reloadSidebarMetadata();
    }, 150);
  }, [reloadSidebarMetadata]);
  useEffect(() => () => { if (metadataRefreshTimer.current) clearTimeout(metadataRefreshTimer.current); }, []);

  const flushQueuedSessionRows = useCallback(() => {
    if (queuedSessionRowsTimerRef.current) {
      clearTimeout(queuedSessionRowsTimerRef.current);
      queuedSessionRowsTimerRef.current = null;
    }
    const rows = [...queuedSessionRowsRef.current.values()];
    queuedSessionRowsRef.current.clear();
    if (rows.length > 0) {
      recordChatDiagnosticCounter("sidebar_session_patch_flush");
      setSessions((prev) => applySessionRows(prev, rows));
    }
  }, []);

  const queueSessionRowPatch = useCallback((row: SessionInfo, immediate = false) => {
    recordChatDiagnosticCounter(immediate ? "sidebar_session_patch_immediate" : "sidebar_session_patch_queued");
    if (immediate) {
      queuedSessionRowsRef.current.delete(row.id);
      setSessions((prev) => applySessionRows(prev, [row]));
      return;
    }
    queuedSessionRowsRef.current.set(
      row.id,
      mergeSessionRow(queuedSessionRowsRef.current.get(row.id), row),
    );
    if (!queuedSessionRowsTimerRef.current) {
      queuedSessionRowsTimerRef.current = setTimeout(flushQueuedSessionRows, 150);
    }
  }, [flushQueuedSessionRows]);

  useEffect(() => {
    void reloadProjects();
    const refresh = () => { void reloadProjects(); };
    window.addEventListener(SIDEBAR_SCOPE_EVENT, refresh);
    return () => window.removeEventListener(SIDEBAR_SCOPE_EVENT, refresh);
  }, [reloadProjects]);

  // Pins are durable across reloads and may point outside the recent page.
  useEffect(() => {
    if (loadingSessions) return;
    const loaded = new Set(sessions.map((session) => session.id));
    const required = new Set(pinnedIdsRef.current);
    Object.entries(sidebarAttention).forEach(([id, attention]) => {
      if (attention.pending_decision || attention.running) required.add(id);
    });
    required.forEach((id) => { if (!loaded.has(id)) void hydrateSession(id); });
  }, [hydrateSession, loadingSessions, sessions, pinnedIds, sidebarAttention]);

  useEffect(() => () => {
    if (queuedSessionRowsTimerRef.current) clearTimeout(queuedSessionRowsTimerRef.current);
    queuedSessionRowsRef.current.clear();
  }, []);

  // ── Real-time updates (SSE) ──
  useEventBus((env: SparkEventEnvelope) => {
    if (env.topic === "sidebar.metadata_changed") queueSidebarMetadataReload();
    if (env.topic === STATE_SNAPSHOT_TOPIC) void reloadSidebarMetadata();
    if (env.topic === STATE_SNAPSHOT_TOPIC) {
      const snapshot = env.data.snapshot as WebStateSnapshotV1 | undefined;
      if (snapshot?.shells) {
        normalizedWebState.replaceShells(snapshot.shells);
        if (snapshot.detail) {
          const now = Date.now();
          normalizedWebState.setDetail({
            sessionId: snapshot.detail.session_id,
            messages: snapshot.detail.messages,
            status: snapshot.detail.turn?.turn_active ? "streaming" : "idle",
            mountedAt: now,
            lastAccessedAt: now,
            settled: !snapshot.detail.turn?.turn_active,
          });
          normalizedWebState.expireIdleDetails(snapshot.detail.session_id, now);
        }
        setSessions(normalizedWebState.selectShells() as SessionInfo[]);
        nextSessionsOffsetRef.current = snapshot.shells.length;
        setHasMoreSessions(snapshotHasMoreSessions(snapshot));
      }
      return;
    }
    // chat.turn_done is the authoritative live completion edge. The sessions
    // projection can arrive a little later, which previously left the inbox
    // card saying Working until a full page refresh reconciled it.
    if (env.topic === "chat.turn_done") {
      void reloadSidebarMetadata();
      const data = env.data as { session_id?: string };
      const sid = data.session_id ?? env.session_id ?? "";
      if (sid) {
        queuedSessionRowsRef.current.delete(sid);
        setSessions((prev) => prev.map((session) => (
          session.id === sid ? { ...session, is_active: false } : session
        )));
      }
      return;
    }
    if (env.topic === "chat.status" && !sidebarAttention[env.session_id ?? ""]?.running) queueSidebarMetadataReload();
    if (env.topic === "chat.approval_requested" || env.topic === "chat.input_requested" || env.topic === "chat.approval_resolved" || env.topic === "chat.input_resolved") void reloadSidebarMetadata();
    if (env.topic !== "sessions.changed") return;
    const data = env.data as { action?: string; session_id?: string; session?: SessionInfo };
    if (data.action === "sidebar_metadata") { queueSidebarMetadataReload(); return; }
    if (data.action === "created") queueSidebarMetadataReload();
    const sid = data.session_id ?? "";

    if (data.action === "deleted" && sid) {
      metadataRequestRef.current += 1;
      const remaining = { ...metadataRef.current };
      delete remaining[sid];
      metadataRef.current = remaining;
      setSidebarMetadata(remaining);
      queueSidebarMetadataReload();
      normalizedWebState.removeShell(sid);
      dismissSessionNotification(sid);
      lastMessageCountRef.current.delete(sid);
      notifiedMessageCountRef.current.delete(sid);
      queuedSessionRowsRef.current.delete(sid);
      setSessions((prev) => prev.filter((s) => s.id !== sid));
      if (selectedIdRef.current === sid) {
        setSelectedId(null);
        setComposingFor(null);
      }
      return;
    }

    if (data.session) {
      const row = data.session;
      normalizedWebState.upsertShell(row);
      const newCount = row.message_count ?? 0;
      const lastCount = lastMessageCountRef.current.get(row.id) ?? 0;
      const notifiedCount = notifiedMessageCountRef.current.get(row.id) ?? 0;
      const isSelected = row.id === selectedIdRef.current;
      const notificationTitle = threadTitle(row) || "Untitled thread";
      const notificationPreview = row.preview?.trim() ? row.preview : null;

      // Detect new messages on a thread the user isn't currently viewing →
      // show an unread notification dot + bell entry.
      if (isSelected) {
        markSessionRead(row.id);
        notifiedMessageCountRef.current.set(row.id, Math.max(notifiedCount, newCount));
      } else if (newCount > notifiedCount && !row.is_active) {
        addSessionNotification(row.id, notificationTitle, notificationPreview);
        notifiedMessageCountRef.current.set(row.id, newCount);
      } else if (!row.is_active && getUnreadSessionIds().has(row.id)) {
        addSessionNotification(row.id, notificationTitle, notificationPreview);
      }
      lastMessageCountRef.current.set(row.id, Math.max(lastCount, newCount));

      queueSessionRowPatch(row, isSelected);
    }
  });

  // ── Search (debounced FTS with client-side fallback) ──
  useEffect(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    if (!searchQ.trim()) {
      searchRequestRef.current += 1;
      setSearchResults(null);
      setSearching(false);
      return;
    }

    const localResults = filterSessionsLocally(sessionsRef.current, searchQ);
    // Filtering the loaded page is immediate. Full-history FTS is deliberately
    // debounced so normal typing cannot fan out one database query per key.
    const requestId = ++searchRequestRef.current;
    searchDebounceRef.current = setTimeout(async () => {
      try {
        const res = await api.searchSessions(searchQ.trim(), 100);
        const loaded = new Map(sessionsRef.current.map((session) => [session.id, session]));
        const hydrated = res.results.map((result) => {
          const existing = loaded.get(result.session_id);
          if (existing) return existing;
          const provisional = sessionInfoFromDetail(
            { id: result.session_id, title: result.title },
            result,
          );
          setSessions((prev) => mergeSessionPage(prev, [provisional]));
          void hydrateSession(result.session_id, result).then((row) => {
            if (!row || requestId !== searchRequestRef.current) return;
            setSearchResults((prev) => prev?.map((session) => (
              session.id === row.id ? mergeSessionRow(session, row) : session
            )) ?? prev);
          });
          return provisional;
        });
        if (requestId === searchRequestRef.current) {
          setSearchResults(mergeSearchRows(localResults, hydrated));
        }
      } catch {
        // The immediate loaded-page result remains useful if FTS is unavailable.
        if (requestId === searchRequestRef.current) setSearchResults(localResults);
      } finally {
        if (requestId === searchRequestRef.current) setSearching(false);
      }
    }, 250);
  }, [hydrateSession, searchQ]);

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
          notifiedMessageCountRef.current.set(id, session.message_count);
        }
        return prev;
      });
    }
    if (id && !sessionsRef.current.some((session) => session.id === id)) void hydrateSession(id);
    setSelectedId(id);
    try {
      if (id) writeSidebarPreference(SELECTED_SESSION_KEY, id);
      else writeSidebarPreference(SELECTED_SESSION_KEY, "");
    } catch { /* private or unavailable storage: memory state still works */ }
    setComposingFor(null);
  }, [hydrateSession]);

  const newSession = useCallback(() => {
    setSelectedId(null);
    setComposingFor(null);
    setSearchQ("");
  }, [setSearchQ]);

  const toggleProjectExpanded = useCallback((slug: string) => {
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug);
      else next.add(slug);
      writeSidebarPreference(EXPANDED_KEY, JSON.stringify([...next]));
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
      writeSidebarPreference(EXPANDED_KEY, JSON.stringify([...next]));
      return next;
    });
  }, []);

  const cancelCompose = useCallback(() => setComposingFor(null), []);

  const threadCreated = useCallback((sessionId: string, initialMessage: string, meta?: ThreadCreatedMeta) => {
    const source = meta?.source ?? (meta?.projectSlug ? `workspace:${meta.projectSlug}` : null);
    const projectSlug = meta?.projectSlug ?? slugFromSource(source);
    const now = Date.now() / 1000;
    const optimistic: SessionInfo = {
      id: sessionId,
      source,
      model: null,
      title: initialMessage,
      started_at: now,
      ended_at: null,
      last_active: now,
      is_active: true,
      message_count: 1,
      tool_call_count: 0,
      input_tokens: 0,
      output_tokens: 0,
      preview: initialMessage,
      kanban_status: null,
      estimated_cost_usd: null,
    };
    // Seed the normalized projection as well as React state so an immediate
    // snapshot with zero timestamps cannot erase the local creation time.
    if (!normalizedWebState.selectShell(sessionId)) {
      normalizedWebState.upsertShell(optimistic);
    }
    setPendingInitialMessages((pending) => ({ ...pending, [sessionId]: initialMessage }));
    setComposingFor(null);
    setSelectedId(sessionId);
    if (projectSlug) {
      setExpandedProjects((prev) => {
        const next = new Set(prev);
        next.add(projectSlug);
        writeSidebarPreference(EXPANDED_KEY, JSON.stringify([...next]));
        return next;
      });
    }
    setSessions((prev) => {
      if (prev.some((session) => session.id === sessionId)) {
        return prev.map((session) => (
          session.id === sessionId
            ? { ...session, source: source ?? session.source, last_active: now, is_active: true }
            : session
        ));
      }
      return [optimistic, ...prev];
    });
  }, []);

  const clearPendingInitialMessage = useCallback((sessionId?: string) => {
    setPendingInitialMessages((pending) => {
      if (!sessionId) return {};
      if (!(sessionId in pending)) return pending;
      const next = { ...pending };
      delete next[sessionId];
      return next;
    });
  }, []);

  // Desktop tray "New Chat" + global sidebar "New chat" dispatch this event.
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
        writeSidebarPreference(EXPANDED_KEY, JSON.stringify([...next]));
        return next;
      });
    }
  }, [selectSession, setSearchQ]);

  useEffect(() => {
    const projectTarget = takeGlobalNavTarget("project");
    const threadTarget = projectTarget ? null : takeGlobalNavTarget("thread");
    if (projectTarget) openGlobalTarget(projectTarget);
    if (threadTarget) openGlobalTarget(threadTarget);

    const handler = (event: Event) => {
      const target = (event as CustomEvent<GlobalNavTarget>).detail;
      if (target?.type === "project" || target?.type === "thread") {
        // The store remains mounted across navigation. Consume live targets as
        // well as initial ones so reload cannot reopen an old worktree project.
        takeGlobalNavTarget(target.type);
        openGlobalTarget(target);
      }
    };
    window.addEventListener(GLOBAL_NAV_EVENT, handler);
    return () => window.removeEventListener(GLOBAL_NAV_EVENT, handler);
  }, [openGlobalTarget]);

  // Serialize this client's metadata gestures; other clients are fenced by CAS.
  const mutateSidebar = useCallback(async (id: string, fields: Partial<Omit<SidebarMetadata, "revision">>, expected?: number) => {
    const meta = metadataRef.current[id] ?? DEFAULT_SIDEBAR_METADATA;
    try {
      const result = await api.patchSidebarThread(id, expected ?? meta.revision, fields);
      // Fence a GET started before this acceptance, including snapshots that
      // predate a newly created thread and therefore omit its ID entirely.
      metadataRequestRef.current += 1;
      metadataRef.current = { ...metadataRef.current, [id]: result.metadata };
      setSidebarMetadata(metadataRef.current);
      return result.metadata;
    } catch (error) {
      if (error instanceof SidebarMutationError && error.current) {
        metadataRequestRef.current += 1;
        metadataRef.current = { ...metadataRef.current, [id]: error.current };
        setSidebarMetadata(metadataRef.current);
      }
      throw error;
    }
  }, []);
  const sidebarAction = useCallback((action: () => Promise<void>) => {
    if (busyRef.current) return;
    if (!sidebarMetadataReady) { setSidebarMetadataError("Refresh thread organization before making changes"); return; }
    busyRef.current = true;
    setSidebarBusy(true);
    sidebarMutationErrorRef.current = null;
    setSidebarMetadataError(null);
    void action().catch(async (error) => {
      await reloadSidebarMetadata();
      sidebarMutationErrorRef.current = error instanceof Error ? error.message : "Could not update thread organization";
      setSidebarMetadataError(sidebarMutationErrorRef.current);
    }).finally(() => { busyRef.current = false; setSidebarBusy(false); });
  }, [reloadSidebarMetadata, sidebarMetadataReady]);
  const togglePin = useCallback((id: string) => sidebarAction(async () => {
    const current = metadataRef.current[id] ?? DEFAULT_SIDEBAR_METADATA;
    await mutateSidebar(id, { pinned: !current.pinned });
  }), [mutateSidebar, sidebarAction]);
  const toggleSettled = useCallback((id: string) => sidebarAction(async () => {
    const current = metadataRef.current[id] ?? DEFAULT_SIDEBAR_METADATA;
    const result = await mutateSidebar(id, { settled: !current.settled });
    setSidebarUndo({ id, settled: current.settled, revision: result.revision });
  }), [mutateSidebar, sidebarAction]);
  const undoSidebarChange = useCallback(() => {
    if (!sidebarUndo) return;
    sidebarAction(async () => {
      // Original post-action revision: a newer metadata edit must conflict.
      try {
        await mutateSidebar(sidebarUndo.id, { settled: sidebarUndo.settled }, sidebarUndo.revision);
        setSidebarUndo(null);
      } catch (error) {
        if (error instanceof SidebarMutationError && error.current) setSidebarUndo(null);
        throw error;
      }
    });
  }, [mutateSidebar, sidebarAction, sidebarUndo]);
  const moveSidebarSession = useCallback((id: string, direction: -1 | 1) => sidebarAction(async () => {
    const row = sessionsRef.current.find((session) => session.id === id);
    if (!row) return;
    const entries = metadataRef.current;
    const settled = isEffectivelySettled(row, entries, sidebarAttention[id]);
    const group = sessionsRef.current.filter((session) =>
      isEffectivelySettled(session, entries, sidebarAttention[session.id]) === settled
      && (entries[id]?.pinned ? entries[session.id]?.pinned : session.source === row.source));
    for (const patch of sidebarMovePatches(group, entries, id, direction)) {
      await mutateSidebar(patch.id, { position: patch.position }, patch.revision);
    }
  }), [mutateSidebar, sidebarAction, sidebarAttention]);
  const importLocalPins = useCallback(() => sidebarAction(async () => {
    const legacy: unknown = JSON.parse(localStorage.getItem(PINNED_KEY) ?? "[]");
    if (!Array.isArray(legacy)) return;
    for (const id of legacy) {
      if (typeof id === "string" && metadataRef.current[id]?.revision === 0) await mutateSidebar(id, { pinned: true }, 0);
    }
    writeSidebarPreference("spark-sidebar-pin-import", "v1");
    setCanImportLocalPins(false);
  }), [mutateSidebar, sidebarAction]);

  // ── Mutations ──
  const deleteSession = useCallback(async (id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
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

  const createProject = useCallback(async (request: ProjectCreateRequest | string, template = "scratch"): Promise<string> => {
    const res = await api.createWorkspaceProject(request, template);
    await reloadProjects();
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      next.add(res.slug);
      writeSidebarPreference(EXPANDED_KEY, JSON.stringify([...next]));
      return next;
    });
    return res.slug;
  }, [reloadProjects]);

  const moveSessionToProject = useCallback(async (id: string, slug: string | null) => {
    const source = slug ? `workspace:${slug}` : "web";
    let previous: SessionInfo | null = null;
    setSessions((prev) => prev.map((session) => {
      if (session.id !== id) return session;
      previous = session;
      return { ...session, source };
    }));
    if (slug) {
      setExpandedProjects((prev) => {
        const next = new Set(prev);
        next.add(slug);
        writeSidebarPreference(EXPANDED_KEY, JSON.stringify([...next]));
        return next;
      });
    }
    try {
      const res = await api.moveSession(id, source);
      if (res.session) {
        setSessions((prev) => prev.map((session) => (
          session.id === id ? { ...session, ...res.session } : session
        )));
      }
    } catch (e) {
      if (previous) {
        setSessions((prev) => prev.map((session) => (
          session.id === id ? previous as SessionInfo : session
        )));
      } else {
        void reloadSessions();
      }
      throw e;
    }
  }, [reloadSessions]);

  const renameProject = useCallback(async (slug: string, name: string): Promise<string> => {
    const res = await api.renameWorkspaceProject(slug, name);
    const newSlug = res.slug;
    setProjects((prev) => prev.map((project) => (
      project.slug === slug
        ? { ...project, slug: newSlug, name: res.name, path: res.path, mtime: res.mtime }
        : project
    )));
    setSessions((prev) => prev.map((session) => (
      session.source === `workspace:${slug}`
        ? { ...session, source: `workspace:${newSlug}` }
        : session
    )));
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      if (next.delete(slug)) next.add(newSlug);
      writeSidebarPreference(EXPANDED_KEY, JSON.stringify([...next]));
      return next;
    });
    setComposingFor((prev) => (prev === slug ? newSlug : prev));
    void reloadProjects();
    return newSlug;
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
    loadingMoreSessions,
    hasMoreSessions,
    sessionsError,
    searchQ,
    setSearchQ,
    searchResults,
    searching,
    displayedSessions,
    pinnedIds,
    togglePin,
    sidebarMetadata, sidebarAttention, sidebarMetadataError, sidebarMetadataReady,
    sidebarBusy, sidebarUndo, toggleSettled, undoSidebarChange, moveSidebarSession,
    reloadSidebarMetadata, canImportLocalPins, importLocalPins,
    selectedId,
    selectedSession,
    composingFor,
    sidebarProjectScope,
    setSidebarProjectScope,
    selectSession,
    newSession,
    newProjectThread,
    cancelCompose,
    pendingInitialMessages,
    clearPendingInitialMessage,
    threadCreated,
    unreadSessionIds,
    expandedProjects,
    toggleProjectExpanded,
    deleteSession,
    deleteProject,
    createProject,
    moveSessionToProject,
    renameProject,
    reloadSessions,
    loadMoreSessions,
    reloadProjects,
  };

  return <SessionStoreContext.Provider value={value}>{children}</SessionStoreContext.Provider>;
}

export function useSessionStore(): SessionStoreValue {
  const ctx = useContext(SessionStoreContext);
  if (!ctx) throw new Error("useSessionStore must be used within SessionStoreProvider");
  return ctx;
}
