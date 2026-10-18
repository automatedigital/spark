import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ChatSubagentEventData, ConversationSubagentResponse, SubagentCapabilities, SubagentRun } from "@/lib/api";
import { mergeSubagentLiveEvents, mergeSubagentSnapshot, reconcileSubagentSnapshot } from "@/lib/subagents";
import { BUS_DISCONNECTED_TOPIC, BUS_GAP_TOPIC, BUS_RECONNECTED_TOPIC, BUS_STALE_TOPIC, STATE_SNAPSHOT_TOPIC, useEventBus } from "@/hooks/useEventBus";

type LiveUpdate = { topic: string; data: ChatSubagentEventData };
export type ChildEventPage = { hasMore: boolean; afterId: number | null };

export interface UseSubagentsResult {
  subagents: SubagentRun[];
  capabilities: SubagentCapabilities | null;
  eventPages: Record<string, ChildEventPage>;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  loadSubagentDetail: (subagentId: string, eventLimit?: number, eventAfterId?: number) => Promise<ConversationSubagentResponse | undefined>;
}

export function useSubagents(sessionId: string | null): UseSubagentsResult {
  const [subagents, setSubagents] = useState<SubagentRun[]>([]);
  const [capabilities, setCapabilities] = useState<SubagentCapabilities | null>(null);
  const [snapshotTotal, setSnapshotTotal] = useState<number | null>(null);
  const [eventPages, setEventPages] = useState<Record<string, ChildEventPage>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef(sessionId);
  const stateSession = useRef(sessionId);
  const generation = useRef(0);
  const loadSeq = useRef(0);
  const capabilitySeq = useRef(0);
  const detailSeq = useRef(new Map<string, number>());
  const detailLimits = useRef(new Map<string, number>());
  const detailCursors = useRef(new Map<string, number>());
  const detailHistoryComplete = useRef(new Map<string, boolean>());
  // Each HTTP request keeps only the live updates received since it began.
  // A snapshot has no web-journal cursor: never compare it to session event IDs.
  const requests = useRef(new Map<string, AbortController>());
  const inFlight = useRef(new Set<LiveUpdate[]>());
  const pendingEvents = useRef<LiveUpdate[]>([]);
  const flushHandle = useRef<number | null>(null);
  sessionRef.current = sessionId;

  const refreshCapabilities = useCallback(async () => {
    const sid = sessionRef.current;
    const gen = generation.current;
    const seq = ++capabilitySeq.current;
    setCapabilities(null);
    requests.current.get("capabilities")?.abort();
    if (!sid) return;
    const request = new AbortController();
    requests.current.set("capabilities", request);
    try {
      const value = await api.getSubagentCapabilities(sid, request.signal);
      if (sessionRef.current === sid && generation.current === gen && capabilitySeq.current === seq) {
        setCapabilities(value.schema_version === 1 ? value : null);
      }
    } catch { /* Older/offline servers have unknown support, never assumed support. */ }
  }, []);

  const reload = useCallback(async () => {
    const sid = sessionRef.current;
    const gen = generation.current;
    const seq = ++loadSeq.current;
    if (!sid) { setSubagents([]); setLoading(false); return; }
    const during: LiveUpdate[] = [];
    requests.current.get("list")?.abort();
    const request = new AbortController();
    requests.current.set("list", request);
    inFlight.current.add(during);
    setLoading(true);
    void refreshCapabilities();
    try {
      const snapshot = await api.getConversationSubagents(sid, request.signal);
      if (loadSeq.current !== seq || generation.current !== gen || sessionRef.current !== sid) return;
      setSubagents((prev) => reconcileSubagentSnapshot(prev, snapshot.subagents ?? [], during));
      setSnapshotTotal(snapshot.total ?? null);
      setError(null);
    } catch (e) {
      if (loadSeq.current !== seq || generation.current !== gen || sessionRef.current !== sid) return;
      setError(e instanceof Error ? e.message : "Failed to load subagents.");
    } finally {
      inFlight.current.delete(during);
      if (loadSeq.current === seq && generation.current === gen && sessionRef.current === sid) setLoading(false);
    }
  }, [refreshCapabilities]);

  const loadSubagentDetail = useCallback(async (subagentId: string, eventLimit?: number, eventAfterId?: number) => {
    const sid = sessionRef.current;
    if (!sid || !subagentId) return;
    const gen = generation.current;
    const seq = (detailSeq.current.get(subagentId) ?? 0) + 1;
    detailSeq.current.set(subagentId, seq);
    const limit = Math.min(1000, eventLimit ?? detailLimits.current.get(subagentId) ?? 200);
    detailLimits.current.set(subagentId, limit);
    requests.current.get(subagentId)?.abort();
    const request = new AbortController();
    requests.current.set(subagentId, request);
    const during: LiveUpdate[] = [];
    inFlight.current.add(during);
    try {
      const snapshot = await api.getConversationSubagent(sid, subagentId, limit, request.signal, eventAfterId);
      if (sessionRef.current !== sid || generation.current !== gen || detailSeq.current.get(subagentId) !== seq) return;
      setSubagents((prev) => mergeSubagentLiveEvents(mergeSubagentSnapshot(prev, [snapshot.subagent]), during));
      const priorCursor = detailCursors.current.get(subagentId) ?? 0;
      const pageLastId = Math.max(0, ...(snapshot.subagent.events ?? []).map((event) => Number(event.id) || 0));
      const lastId = Math.max(priorCursor, pageLastId);
      if (lastId) detailCursors.current.set(subagentId, lastId);
      if (typeof snapshot.has_more_events === "boolean" && !(eventAfterId === undefined && priorCursor > pageLastId)) {
        detailHistoryComplete.current.set(subagentId, !snapshot.has_more_events);
        setEventPages((prev) => ({ ...prev, [subagentId]: { hasMore: snapshot.has_more_events!, afterId: snapshot.next_event_after_id ?? null } }));
      }
      setError(null);
      return snapshot;
    } catch (e) {
      if (sessionRef.current !== sid || generation.current !== gen || detailSeq.current.get(subagentId) !== seq) return;
      setError(e instanceof Error ? e.message : "Failed to load subagent detail.");
    } finally { inFlight.current.delete(during); }
  }, []);

  const flushPendingEvents = useCallback(() => {
    flushHandle.current = null;
    const pending = pendingEvents.current;
    pendingEvents.current = [];
    if (pending.length) setSubagents((prev) => mergeSubagentLiveEvents(prev, pending));
  }, []);

  useEffect(() => {
    generation.current += 1;
    stateSession.current = sessionId;
    setSubagents([]);
    setCapabilities(null);
    setSnapshotTotal(null);
    setEventPages({});
    setError(null);
    pendingEvents.current = [];
    inFlight.current.clear();
    detailLimits.current.clear();
    detailCursors.current.clear();
    detailHistoryComplete.current.clear();
    detailSeq.current.clear();
    void reload();
    const activeRequests = requests.current;
    return () => {
      generation.current += 1;
      for (const request of activeRequests.values()) request.abort();
      activeRequests.clear();
    };
  }, [sessionId, reload]);

  useEffect(() => {
    // Capability assertions expire even if a quiet stream never errors.
    const timer = window.setInterval(() => { void refreshCapabilities(); }, 30_000);
    return () => window.clearInterval(timer);
  }, [refreshCapabilities]);

  useEffect(() => () => {
    if (flushHandle.current !== null) window.cancelAnimationFrame(flushHandle.current);
  }, []);

  useEventBus((env) => {
    if ([BUS_DISCONNECTED_TOPIC, BUS_GAP_TOPIC, BUS_STALE_TOPIC].includes(env.topic)) {
      generation.current += 1;
      capabilitySeq.current += 1;
      setCapabilities(null);
      setLoading(false);
      pendingEvents.current = [];
      inFlight.current.clear();
      for (const request of requests.current.values()) request.abort();
      requests.current.clear();
      // Expired epochs invalidate HTTP detail loads too. A new snapshot below
      // replaces old status; no prompt or control action is replayed.
      return;
    }
    if (env.topic === BUS_RECONNECTED_TOPIC || env.topic === STATE_SNAPSHOT_TOPIC) {
      void reload();
      for (const [id, limit] of detailLimits.current) {
        // Refresh the loaded range without automatically consuming unread
        // history. Once caught up, fetch only newly appended event rows.
        void loadSubagentDetail(id, limit, detailHistoryComplete.current.get(id) ? detailCursors.current.get(id) : undefined);
      }
      return;
    }
    if (!env.topic.startsWith("chat.subagent.") || env.session_id !== sessionRef.current) return;
    const update = { topic: env.topic, data: env.data as ChatSubagentEventData };
    for (const buffer of inFlight.current) buffer.push(update);
    pendingEvents.current.push(update);
    if (flushHandle.current === null) flushHandle.current = window.requestAnimationFrame(flushPendingEvents);
    if (!["thinking", "tool_output", "tool_started", "tool_completed"].some((suffix) => env.topic.endsWith(`.${suffix}`))) {
      void refreshCapabilities();
    }
  });

  const current = stateSession.current === sessionId;
  const complete = snapshotTotal !== null && snapshotTotal <= subagents.length;
  const safeCapabilities = capabilities && !complete ? {
    ...capabilities,
    controls: {
      ...capabilities.controls,
      interrupt: { supported: false, reason: "The child list is incomplete. Per-child capability data is required." },
      retry: { supported: false, reason: "The child list is incomplete. Per-child capability data is required." },
    },
  } : capabilities;
  return { subagents: current ? subagents : [], capabilities: current ? safeCapabilities : null, eventPages: current ? eventPages : {}, loading: !current || loading, error: current ? error : null, reload, loadSubagentDetail };
}
