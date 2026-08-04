import { useCallback, useEffect, useRef, useState, type Dispatch, type MutableRefObject, type RefObject, type SetStateAction } from "react";
import { api, type SessionMessage } from "@/lib/api";
import type { SessionStats } from "@/components/chat/SessionInfoBar";
import {
  earlierHistoryRequest,
  hasEarlierFromResponse,
  isCurrentSessionResponse as isCurrentSessionResponseFor,
  prependEarlierMessages,
} from "@/lib/chatHistory";
import {
  mergeSyncedMessages,
  localTurnCache,
  type ChatMessage,
} from "@/lib/chatTranscriptMerge";
import {
  backendTurnStatusLabel,
  recoverTurnStateFromBackend,
  type ChatTurnState,
} from "@/lib/chatTurnState";
import { recordWebEfficiency } from "@/lib/efficiencyMetrics";
import { exactAssistantContent } from "@/lib/exactMessage";
import { MODEL_LOADING_LABEL } from "@/components/chat/StatusPill";
import { readSettledDetail, schedulePersistSettledDetail } from "@/lib/webState";
import {
  chatMessagesFromHistory,
  forkInfoFromResponse,
  latestAssistantContentLength,
  type ChatForkInfo,
} from "./chatSessionControllerHelpers";

const HISTORY_PAGE = 50;
const CHAT_RECOVERY_DEBUG_KEY = "spark:chat-recovery-debug";

type CallbackRef<T extends (...args: never[]) => void> = MutableRefObject<T | null>;

export interface ChatPrependScrollAnchor {
  scrollHeight: number;
  scrollTop: number;
  messageCount: number;
  firstMessageId: string | null;
  anchorIndex: number | null;
  anchorId: string | null;
  anchorTop: number | null;
}

export interface ChatSessionResetInput {
  sessionId: string | null;
  initialTranscript: ChatMessage[];
  initialMessage?: string;
  recoverySequence: number;
}

export interface UseChatSessionControllerOptions {
  sessionId: string | null;
  initialMessage?: string;
  scrollContainerRef: RefObject<HTMLDivElement | null>;
  streamingRef: MutableRefObject<boolean>;
  setStreaming: (active: boolean) => void;
  setTurnState: Dispatch<SetStateAction<ChatTurnState>>;
  onSessionResetRef: MutableRefObject<((input: ChatSessionResetInput) => void) | null>;
  flushPendingStreamRef: CallbackRef<() => void>;
  finalizeAssistantRef: CallbackRef<() => void>;
  syncLiveAssistantSnapshotRef: CallbackRef<(text: string, revision: number, start: number) => void>;
  appendRecoveredStaleTurnNoteRef: CallbackRef<(text: string) => void>;
  onSessionCreated?: (id: string) => void;
  onSessionUpdated?: (id: string) => void;
}

function debugChatRecovery(event: string, payload: unknown): void {
  try {
    const enabled = window.localStorage.getItem(CHAT_RECOVERY_DEBUG_KEY);
    if (enabled !== "1" && enabled !== "true") return;
    console.debug(`[spark-chat-recovery] ${event}`, payload);
  } catch {
    /* debug logging is best-effort */
  }
}

export function useChatSessionController({
  sessionId,
  initialMessage,
  scrollContainerRef,
  streamingRef,
  setStreaming,
  setTurnState,
  onSessionResetRef,
  flushPendingStreamRef,
  finalizeAssistantRef,
  syncLiveAssistantSnapshotRef,
  appendRecoveredStaleTurnNoteRef,
  onSessionCreated,
  onSessionUpdated,
}: UseChatSessionControllerOptions) {
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(sessionId);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [hasEarlier, setHasEarlier] = useState(false);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLabel, setStatusLabel] = useState<string | null>(null);
  const [sessionStats, setSessionStats] = useState<SessionStats>({});
  const [forkInfo, setForkInfo] = useState<ChatForkInfo | null>(null);
  const [recoveryPollCount, setRecoveryPollCount] = useState(0);

  const activeSessionRef = useRef<string | null>(sessionId);
  const activeSessionAliasesRef = useRef<Set<string>>(new Set(sessionId ? [sessionId] : []));
  const sessionRecoverySeqRef = useRef(0);
  const activeTurnSessionIdRef = useRef<string | null>(null);
  const streamTextCharsRef = useRef(0);
  const prependScrollAnchorRef = useRef<ChatPrependScrollAnchor | null>(null);
  const resyncInFlightRef = useRef(false);
  const exactAssistantContentRef = useRef<Map<string, string>>(new Map());
  const exactSearchRequestKeyRef = useRef("");
  const onSessionCreatedRef = useRef(onSessionCreated);
  const onSessionUpdatedRef = useRef(onSessionUpdated);

  onSessionCreatedRef.current = onSessionCreated;
  onSessionUpdatedRef.current = onSessionUpdated;
  activeSessionRef.current = activeSessionId;
  if (activeSessionId) activeSessionAliasesRef.current.add(activeSessionId);

  const rememberActiveSessionAliases = useCallback((...ids: Array<string | null | undefined>) => {
    ids.forEach((id) => {
      if (id) activeSessionAliasesRef.current.add(id);
    });
  }, []);

  const resetActiveSessionAliases = useCallback((...ids: Array<string | null | undefined>) => {
    activeSessionAliasesRef.current = new Set(ids.filter((id): id is string => Boolean(id)));
  }, []);

  const isCurrentSessionResponse = useCallback((recoverySequence: number, ...ids: Array<string | null | undefined>) => (
    isCurrentSessionResponseFor(
      recoverySequence,
      sessionRecoverySeqRef.current,
      activeSessionRef.current,
      activeSessionAliasesRef.current,
      ...ids,
    )
  ), []);

  const mergeHistoryResponse = useCallback((
    response: Awaited<ReturnType<typeof api.getSessionMessages>>,
    requestedSessionId: string,
    recoverySequence: number,
    options: {
      baseMessages?: ChatMessage[];
      prepend?: boolean;
      preserveLocalAssistantPrefix?: boolean;
      preferSyncedAssistants?: boolean;
    } = {},
  ): boolean => {
    if (!isCurrentSessionResponse(recoverySequence, requestedSessionId, response.session_id)) return false;
    rememberActiveSessionAliases(requestedSessionId, response.session_id);
    if (response.session_id && response.session_id !== activeSessionRef.current) {
      activeSessionRef.current = response.session_id;
      setActiveSessionId(response.session_id);
    }
    const mapped = chatMessagesFromHistory(response.messages);
    if (options.prepend) {
      setChatMessages((previous) => {
        const next = prependEarlierMessages(previous, mapped);
        if (next === previous) prependScrollAnchorRef.current = null;
        return next;
      });
    } else {
      setChatMessages((previous) => {
        const merged = mergeSyncedMessages(
          mapped,
          options.baseMessages ?? previous,
          response.session_id ?? requestedSessionId,
          {
            preserveLocalAssistantPrefix: options.preserveLocalAssistantPrefix,
            preferSyncedAssistants: options.preferSyncedAssistants,
            syncedComplete: !(response.has_earlier ?? false),
          },
        );
        if (requestedSessionId !== activeSessionRef.current) return merged;
        const liveApprovals = previous.filter((message) => (
          message.role === "approval" && !merged.some((synced) => synced.id === message.id)
        ));
        return liveApprovals.length > 0 ? [...merged, ...liveApprovals] : merged;
      });
    }
    setHasEarlier(hasEarlierFromResponse(response.has_earlier));
    if (activeTurnSessionIdRef.current) {
      streamTextCharsRef.current = Math.max(
        streamTextCharsRef.current,
        latestAssistantContentLength(mapped),
      );
    }
    return true;
  }, [isCurrentSessionResponse, rememberActiveSessionAliases]);

  const loadHistoryPage = useCallback(async (
    requestedSessionId: string,
    recoverySequence: number,
    options: Parameters<typeof mergeHistoryResponse>[3] = {},
  ) => {
    const response = await api.getSessionMessages(requestedSessionId, HISTORY_PAGE);
    mergeHistoryResponse(response, requestedSessionId, recoverySequence, options);
    return response;
  }, [mergeHistoryResponse]);

  const refreshLatestTranscript = useCallback(async (options: {
    sessionId?: string;
    persistSequence?: number;
    syncTail?: boolean;
  } = {}) => {
    const requestedSessionId = options.sessionId ?? activeSessionRef.current;
    if (!requestedSessionId) return null;
    const recoverySequence = sessionRecoverySeqRef.current;
    setLoadingHistory(true);
    try {
      const response = await loadHistoryPage(requestedSessionId, recoverySequence, {
        preferSyncedAssistants: true,
      });
      if (options.persistSequence !== undefined) {
        schedulePersistSettledDetail(
          response.session_id ?? requestedSessionId,
          response.messages,
          options.persistSequence,
          true,
        );
      }
      if (options.syncTail) {
        window.setTimeout(() => {
          void api.getSessionMessages(requestedSessionId, 20).then((tailResponse) => {
            if (!isCurrentSessionResponse(recoverySequence, requestedSessionId, tailResponse.session_id)) return;
            rememberActiveSessionAliases(requestedSessionId, tailResponse.session_id);
            const tail = tailResponse.messages.filter((message) => message.role === "user");
            if (tail.length === 0) return;
            const tailByContent = new Map(tail.map((message, index) => [
              message.content ?? "",
              message.message_index ?? tailResponse.messages.indexOf(tail[index]!),
            ]));
            setChatMessages((previous) => {
              let changed = false;
              const next = previous.map((message) => {
                if (message.role !== "user" || message.sessionIdx != null) return message;
                const newIndex = tailByContent.get(message.content);
                if (newIndex == null) return message;
                changed = true;
                return { ...message, sessionIdx: newIndex };
              });
              return changed ? next : previous;
            });
          }).catch(() => {});
        }, 500);
      }
      return response;
    } finally {
      setLoadingHistory(false);
    }
  }, [isCurrentSessionResponse, loadHistoryPage, rememberActiveSessionAliases]);

  const resyncTurnState = useCallback(async (options: { allowIdle?: boolean } = {}) => {
    const sid = activeSessionRef.current;
    if (!sid || (!streamingRef.current && !options.allowIdle) || resyncInFlightRef.current) return;
    const recoverySequence = sessionRecoverySeqRef.current;
    resyncInFlightRef.current = true;
    setRecoveryPollCount((count) => count + 1);
    recordWebEfficiency("httpPolls");
    recordWebEfficiency("streamRecoveryActions");
    try {
      const status = await api.getTurnStatus(sid);
      debugChatRecovery("resync-turn-status", status.diagnostics ?? status);
      if (!isCurrentSessionResponse(
        recoverySequence,
        sid,
        status.resolved_session_id,
        status.latest_session_id,
        status.active_turn_session_id,
      )) return;
      rememberActiveSessionAliases(
        sid,
        status.resolved_session_id,
        status.latest_session_id,
        status.active_turn_session_id,
      );
      if (!status.turn_active) {
        const wasStreaming = streamingRef.current;
        activeTurnSessionIdRef.current = null;
        flushPendingStreamRef.current?.();
        finalizeAssistantRef.current?.();
        setStreaming(false);
        setStatusLabel(null);
        try {
          const response = await loadHistoryPage(sid, recoverySequence, { preferSyncedAssistants: true });
          const hasAssistant = chatMessagesFromHistory(response.messages).some(
            (message) => message.role === "assistant" && message.content.trim(),
          );
          if (wasStreaming && !hasAssistant) {
            appendRecoveredStaleTurnNoteRef.current?.(
              "The previous response stopped before Spark saved an assistant reply. You can retry this message.",
            );
          }
        } catch {
          if (wasStreaming) {
            appendRecoveredStaleTurnNoteRef.current?.(
              "Spark lost the live response state while reconnecting. You can retry or send a follow-up.",
            );
          }
        }
      } else {
        const snapshotSessionId = status.active_turn_session_id ?? sid;
        activeTurnSessionIdRef.current = snapshotSessionId;
        setTurnState(recoverTurnStateFromBackend({
          turnActive: true,
          phase: status.phase,
          state: status.state,
          interruptRequested: status.interrupt_requested,
        }));
        setStatusLabel(backendTurnStatusLabel({
          turnActive: true,
          phase: status.phase,
          state: status.state,
          status: status.status,
          idleForSeconds: status.idle_for_seconds,
        }) ?? MODEL_LOADING_LABEL);
        try {
          const snapshot = await api.getStreamSnapshot(
            snapshotSessionId,
            streamTextCharsRef.current > 0 ? { afterChars: streamTextCharsRef.current } : {},
          );
          debugChatRecovery("resync-stream-snapshot", snapshot.diagnostics ?? snapshot);
          if (!isCurrentSessionResponse(
            recoverySequence,
            sid,
            snapshot.resolved_session_id,
            snapshot.latest_session_id,
            snapshot.active_turn_session_id,
          )) return;
          rememberActiveSessionAliases(
            sid,
            snapshot.resolved_session_id,
            snapshot.latest_session_id,
            snapshot.active_turn_session_id,
          );
          activeTurnSessionIdRef.current = snapshot.turn_active
            ? snapshot.active_turn_session_id ?? snapshotSessionId
            : null;
          if (snapshot.stream_text) {
            syncLiveAssistantSnapshotRef.current?.(
              snapshot.stream_text,
              snapshot.stream_revision,
              snapshot.stream_text_start ?? 0,
            );
          }
          if (!snapshot.turn_active) {
            activeTurnSessionIdRef.current = null;
            flushPendingStreamRef.current?.();
            finalizeAssistantRef.current?.();
            setStreaming(false);
            setStatusLabel("Finalizing from saved history…");
            try {
              await loadHistoryPage(
                snapshot.latest_session_id ?? snapshotSessionId,
                recoverySequence,
                { preferSyncedAssistants: true },
              );
            } finally {
              setStatusLabel(null);
            }
          }
        } catch {
          /* snapshot recovery is best-effort */
        }
      }
    } catch {
      /* network blip — leave state untouched, watchdog will retry */
    } finally {
      resyncInFlightRef.current = false;
    }
  }, [
    appendRecoveredStaleTurnNoteRef,
    finalizeAssistantRef,
    flushPendingStreamRef,
    isCurrentSessionResponse,
    loadHistoryPage,
    rememberActiveSessionAliases,
    setStreaming,
    setTurnState,
    streamingRef,
    syncLiveAssistantSnapshotRef,
  ]);

  useEffect(() => {
    if (sessionId && sessionId === activeSessionRef.current && streamingRef.current) return;

    setActiveSessionId(sessionId);
    activeSessionRef.current = sessionId;
    resetActiveSessionAliases(sessionId);
    const recoverySequence = ++sessionRecoverySeqRef.current;
    const optimistic: ChatMessage[] = initialMessage
      ? [{ id: `optimistic:${recoverySequence}`, role: "user", content: initialMessage }]
      : [];
    const settledCache = sessionId ? readSettledDetail(sessionId) : null;
    const cachedTranscript = sessionId
      ? localTurnCache.get(sessionId)
        ?? (settledCache ? chatMessagesFromHistory(settledCache.messages) : [])
      : [];
    const initialTranscript = cachedTranscript.length > 0 ? cachedTranscript : optimistic;

    setChatMessages(initialTranscript);
    setError(null);
    setStatusLabel(initialMessage ? MODEL_LOADING_LABEL : null);
    setStreaming(Boolean(initialMessage));
    setLoadingHistory(false);
    setHasEarlier(false);
    setSessionStats({});
    setForkInfo(null);
    activeTurnSessionIdRef.current = null;
    streamTextCharsRef.current = latestAssistantContentLength(initialTranscript);
    prependScrollAnchorRef.current = null;
    exactAssistantContentRef.current.clear();
    exactSearchRequestKeyRef.current = "";
    onSessionResetRef.current?.({
      sessionId,
      initialTranscript,
      initialMessage,
      recoverySequence,
    });

    if (!sessionId) return;
    let cancelled = false;
    const recoveryStillCurrent = (...ids: Array<string | null | undefined>) => (
      !cancelled && isCurrentSessionResponse(recoverySequence, sessionId, ...ids)
    );

    void api.getTurnStatus(sessionId).then(async (status) => {
      debugChatRecovery("initial-turn-status", status.diagnostics ?? status);
      if (!recoveryStillCurrent(
        status.resolved_session_id,
        status.latest_session_id,
        status.active_turn_session_id,
      )) return;
      rememberActiveSessionAliases(
        sessionId,
        status.resolved_session_id,
        status.latest_session_id,
        status.active_turn_session_id,
      );
      activeTurnSessionIdRef.current = status.turn_active
        ? status.active_turn_session_id ?? sessionId
        : null;
      setTurnState(recoverTurnStateFromBackend({
        turnActive: status.turn_active,
        phase: status.phase,
        state: status.state,
        interruptRequested: status.interrupt_requested,
      }));
      setStatusLabel(backendTurnStatusLabel({
        turnActive: status.turn_active,
        phase: status.phase,
        state: status.state,
        status: status.status,
        idleForSeconds: status.idle_for_seconds,
      }));
      if (!status.turn_active) {
        flushPendingStreamRef.current?.();
        finalizeAssistantRef.current?.();
        try {
          await loadHistoryPage(sessionId, recoverySequence, {
            baseMessages: initialTranscript.length > 0 ? initialTranscript : optimistic,
            preferSyncedAssistants: true,
          });
        } catch {
          /* history recovery is best-effort */
        }
        return;
      }

      try {
        const snapshotSessionId = status.active_turn_session_id ?? sessionId;
        const snapshot = await api.getStreamSnapshot(
          snapshotSessionId,
          streamTextCharsRef.current > 0 ? { afterChars: streamTextCharsRef.current } : {},
        );
        debugChatRecovery("initial-stream-snapshot", snapshot.diagnostics ?? snapshot);
        if (!recoveryStillCurrent(
          snapshot.resolved_session_id,
          snapshot.latest_session_id,
          snapshot.active_turn_session_id,
        )) return;
        rememberActiveSessionAliases(
          snapshot.resolved_session_id,
          snapshot.latest_session_id,
          snapshot.active_turn_session_id,
        );
        activeTurnSessionIdRef.current = snapshot.turn_active
          ? snapshot.active_turn_session_id ?? snapshotSessionId
          : null;
        if (snapshot.stream_text) {
          syncLiveAssistantSnapshotRef.current?.(
            snapshot.stream_text,
            snapshot.stream_revision,
            snapshot.stream_text_start ?? 0,
          );
        }
        if (!snapshot.turn_active) {
          setStreaming(false);
          setStatusLabel("Finalizing from saved history…");
          flushPendingStreamRef.current?.();
          finalizeAssistantRef.current?.();
          try {
            await loadHistoryPage(sessionId, recoverySequence, { preferSyncedAssistants: true });
          } catch {
            /* final history recovery is best-effort */
          } finally {
            setStatusLabel(null);
          }
        }
      } catch {
        /* snapshot hydration is best-effort */
      }
    }).catch(() => {
      /* selected-session turn recovery is best-effort */
    });

    setLoadingHistory(true);
    void api.getSessionForks(sessionId).then((info) => {
      if (recoveryStillCurrent()) setForkInfo(forkInfoFromResponse(info));
    }).catch(() => {});
    void api.getSessionMessages(sessionId, HISTORY_PAGE).then((response) => {
      if (!recoveryStillCurrent(response.session_id)) return;
      mergeHistoryResponse(response, sessionId, recoverySequence, {
        baseMessages: initialTranscript.length > 0 ? initialTranscript : optimistic,
        preserveLocalAssistantPrefix: Boolean(activeTurnSessionIdRef.current),
      });
      const mapped = chatMessagesFromHistory(response.messages);
      if (streamingRef.current && !activeTurnSessionIdRef.current && mapped.some((message) => message.role === "assistant")) {
        setStreaming(false);
        setStatusLabel(null);
      }
      const warmSessionId = response.session_id ?? sessionId;
      window.setTimeout(() => {
        if (activeSessionRef.current === warmSessionId || activeSessionAliasesRef.current.has(warmSessionId)) {
          void api.warmSession(warmSessionId).catch(() => {});
        }
      }, 400);
    }).catch(() => {
      if (!initialMessage) setError("Failed to load conversation history.");
    }).finally(() => setLoadingHistory(false));

    return () => {
      cancelled = true;
    };
    // Session changes intentionally start a new guarded request sequence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const doFork = useCallback(async (fromSessionIdx?: number) => {
    const sid = activeSessionRef.current;
    if (!sid) return;
    try {
      const result = await api.forkConversation(sid, fromSessionIdx);
      const recoverySequence = ++sessionRecoverySeqRef.current;
      resetActiveSessionAliases(result.session_id);
      activeSessionRef.current = result.session_id;
      activeTurnSessionIdRef.current = null;
      setActiveSessionId(result.session_id);
      setChatMessages([]);
      setHasEarlier(false);
      setLoadingHistory(true);
      onSessionCreatedRef.current?.(result.session_id);
      const response = await api.getSessionMessages(result.session_id);
      if (!isCurrentSessionResponse(recoverySequence, result.session_id, response.session_id)) return;
      mergeHistoryResponse(response, result.session_id, recoverySequence);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingHistory(false);
    }
  }, [isCurrentSessionResponse, mergeHistoryResponse, resetActiveSessionAliases]);

  const doRetry = useCallback(async (messageIndex: number, edited?: string) => {
    const sid = activeSessionRef.current;
    if (!sid || streamingRef.current) return;
    try {
      await api.retryConversation(sid, messageIndex, edited);
      setStreaming(true);
      setStatusLabel(MODEL_LOADING_LABEL);
      streamTextCharsRef.current = 0;
      setTurnState((previous) => previous === "stopping" || previous === "redirecting" ? previous : "starting");
      setChatMessages((previous) => {
        const next = [...previous];
        while (next.length > 0) {
          const last = next[next.length - 1];
          if (last?.role === "assistant" || last?.role === "tool" || last?.role === "reasoning" || last?.role === "note") {
            next.pop();
            continue;
          }
          if (last?.role === "user" && last.sessionIdx === messageIndex && edited != null) {
            next[next.length - 1] = { ...last, content: edited };
          }
          break;
        }
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setStreaming, setTurnState, streamingRef]);

  const loadEarlierMessages = useCallback(async () => {
    const request = earlierHistoryRequest({
      sessionId: activeSessionRef.current,
      loadingEarlier,
      messages: chatMessages,
      limit: HISTORY_PAGE,
    });
    if (!request) return;
    const recoverySequence = sessionRecoverySeqRef.current;
    const scrollElement = scrollContainerRef.current;
    const scrollRect = scrollElement?.getBoundingClientRect();
    const visibleAnchor = scrollElement && scrollRect
      ? Array.from(scrollElement.querySelectorAll<HTMLElement>("[data-row-id]")).find((row) => {
          const rect = row.getBoundingClientRect();
          return rect.bottom > scrollRect.top && rect.top < scrollRect.bottom;
        })
      : null;
    const visibleAnchorId = visibleAnchor?.dataset.rowId ?? null;
    const transcriptAnchorIndex = visibleAnchorId
      ? chatMessages.findIndex((message) => message.id === visibleAnchorId)
      : -1;
    prependScrollAnchorRef.current = scrollElement
      ? {
          scrollHeight: scrollElement.scrollHeight,
          scrollTop: scrollElement.scrollTop,
          messageCount: chatMessages.length,
          firstMessageId: chatMessages[0]?.id ?? null,
          anchorIndex: transcriptAnchorIndex >= 0
            ? transcriptAnchorIndex
            : visibleAnchor?.dataset.index ? Number(visibleAnchor.dataset.index) : null,
          anchorId: visibleAnchorId,
          anchorTop: visibleAnchor?.getBoundingClientRect().top ?? null,
        }
      : null;
    setLoadingEarlier(true);
    try {
      const response = await api.getSessionMessages(request.sessionId, request.limit, request.beforeId);
      if (!isCurrentSessionResponse(recoverySequence, request.sessionId, response.session_id)) return;
      rememberActiveSessionAliases(request.sessionId, response.session_id);
      const mapped = chatMessagesFromHistory(response.messages);
      setChatMessages((previous) => {
        const next = prependEarlierMessages(previous, mapped);
        if (next === previous) prependScrollAnchorRef.current = null;
        return next;
      });
      setHasEarlier(hasEarlierFromResponse(response.has_earlier));
    } catch {
      prependScrollAnchorRef.current = null;
    } finally {
      setLoadingEarlier(false);
    }
  }, [chatMessages, isCurrentSessionResponse, loadingEarlier, rememberActiveSessionAliases, scrollContainerRef]);

  const loadExactMessages = useCallback(async () => {
    const sid = activeSessionRef.current;
    if (!sid) return [] as SessionMessage[];
    const response = await api.getSessionMessages(sid);
    for (const message of response.messages) {
      if (message.role === "assistant" && message.id != null && message.content != null) {
        exactAssistantContentRef.current.set(`db:${message.id}`, message.content);
      }
    }
    return response.messages;
  }, []);

  const fetchExactAssistant = useCallback(async (
    message: Extract<ChatMessage, { role: "assistant" }>,
  ) => {
    if (!message.liveOmittedChars) return message.content;
    const cached = exactAssistantContentRef.current.get(message.id);
    if (cached != null) return cached;
    const messages = await loadExactMessages();
    const exact = exactAssistantContent(messages, message.id) ?? message.content;
    exactAssistantContentRef.current.set(message.id, exact);
    return exact;
  }, [loadExactMessages]);

  return {
    chatMessages,
    setChatMessages,
    activeSessionId,
    setActiveSessionId,
    loadingHistory,
    setLoadingHistory,
    hasEarlier,
    setHasEarlier,
    loadingEarlier,
    error,
    setError,
    statusLabel,
    setStatusLabel,
    sessionStats,
    setSessionStats,
    forkInfo,
    recoveryPollCount,
    activeSessionRef,
    activeSessionAliasesRef,
    sessionRecoverySeqRef,
    activeTurnSessionIdRef,
    streamTextCharsRef,
    prependScrollAnchorRef,
    rememberActiveSessionAliases,
    isCurrentSessionResponse,
    resyncTurnState,
    doFork,
    doRetry,
    refreshLatestTranscript,
    loadEarlierMessages,
    loadExactMessages,
    fetchExactAssistant,
  };
}
