import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ChatSubagentEventData, SubagentRun } from "@/lib/api";
import { mergeSubagentLiveEvents, mergeSubagentSnapshot } from "@/lib/subagents";
import { BUS_RECONNECTED_TOPIC, useEventBus } from "@/hooks/useEventBus";

export interface UseSubagentsResult {
  subagents: SubagentRun[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  loadSubagentDetail: (subagentId: string) => Promise<void>;
}

function isMissingEndpoint(error: unknown): boolean {
  return Boolean(
    error instanceof Error
      && ((error as Error & { status?: number }).status === 404 || error.message.startsWith("404")),
  );
}

export function useSubagents(sessionId: string | null): UseSubagentsResult {
  const [subagents, setSubagents] = useState<SubagentRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sessionRef = useRef(sessionId);
  const loadSeqRef = useRef(0);
  const detailedRunIdsRef = useRef(new Set<string>());
  const pendingEventsRef = useRef<Array<{ topic: string; data: ChatSubagentEventData }>>([]);
  const flushHandleRef = useRef<number | null>(null);

  sessionRef.current = sessionId;

  const reload = useCallback(async () => {
    const sid = sessionRef.current;
    if (!sid) {
      setSubagents([]);
      setError(null);
      setLoading(false);
      return;
    }
    const seq = loadSeqRef.current + 1;
    loadSeqRef.current = seq;
    setLoading(true);
    try {
      const snapshot = await api.getConversationSubagents(sid);
      if (loadSeqRef.current !== seq || sessionRef.current !== sid) return;
      setSubagents((prev) => mergeSubagentSnapshot(prev, snapshot.subagents ?? []));
      setError(null);
    } catch (e) {
      if (loadSeqRef.current !== seq || sessionRef.current !== sid) return;
      if (isMissingEndpoint(e)) {
        setError(null);
        return;
      }
      setError(e instanceof Error ? e.message : "Failed to load subagents.");
    } finally {
      if (loadSeqRef.current === seq && sessionRef.current === sid) setLoading(false);
    }
  }, []);

  const loadSubagentDetail = useCallback(async (subagentId: string) => {
    const sid = sessionRef.current;
    if (!sid || !subagentId) return;
    detailedRunIdsRef.current.add(subagentId);
    try {
      const snapshot = await api.getConversationSubagent(sid, subagentId);
      if (sessionRef.current !== sid) return;
      setSubagents((prev) => mergeSubagentSnapshot(prev, [snapshot.subagent]));
      setError(null);
    } catch (e) {
      if (sessionRef.current !== sid) return;
      setError(e instanceof Error ? e.message : "Failed to load subagent detail.");
    }
  }, []);

  const flushPendingEvents = useCallback(() => {
    flushHandleRef.current = null;
    const pending = pendingEventsRef.current;
    if (pending.length === 0) return;
    pendingEventsRef.current = [];
    setSubagents((prev) => mergeSubagentLiveEvents(prev, pending));
  }, []);

  const queueLiveEvent = useCallback((topic: string, data: ChatSubagentEventData) => {
    pendingEventsRef.current.push({ topic, data });
    if (flushHandleRef.current !== null) return;
    const schedule =
      typeof window !== "undefined" && typeof window.requestAnimationFrame === "function"
        ? window.requestAnimationFrame
        : (cb: FrameRequestCallback) => window.setTimeout(() => cb(Date.now()), 16);
    flushHandleRef.current = schedule(flushPendingEvents);
  }, [flushPendingEvents]);

  useEffect(() => {
    setSubagents([]);
    setError(null);
    pendingEventsRef.current = [];
    detailedRunIdsRef.current.clear();
    void reload();
  }, [sessionId, reload]);

  useEffect(() => () => {
    if (flushHandleRef.current === null) return;
    if (typeof window !== "undefined" && typeof window.cancelAnimationFrame === "function") {
      window.cancelAnimationFrame(flushHandleRef.current);
    } else {
      window.clearTimeout(flushHandleRef.current);
    }
  }, []);

  useEventBus((env) => {
    if (env.topic === BUS_RECONNECTED_TOPIC) {
      void reload();
      for (const subagentId of detailedRunIdsRef.current) {
        void loadSubagentDetail(subagentId);
      }
      return;
    }
    if (!env.topic.startsWith("chat.subagent.")) return;
    const sid = env.session_id ?? null;
    if (!sid || sid !== sessionRef.current) return;
    const data = env.data as ChatSubagentEventData;
    queueLiveEvent(env.topic, data);
  });

  return { subagents, loading, error, reload, loadSubagentDetail };
}
