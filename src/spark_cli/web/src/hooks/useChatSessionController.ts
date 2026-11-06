import { useMessageAnchor } from "./useMessageAnchor";
import { useCallback, useEffect, useRef, useState, type Dispatch, type MutableRefObject, type RefObject, type SetStateAction } from "react";
import { api, type ChatRecoveryResponse, type SessionMessage } from "@/lib/api";
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
import { isAuthoritativeRecoveryFor } from "@/lib/chatRecovery";
import { recordWebEfficiency } from "@/lib/efficiencyMetrics";
import { exactAssistantContent } from "@/lib/exactMessage";
import { isChatPanelScopeCurrent, type ChatPanelOwner, type OwnedSessionAdoption } from "@/lib/chatPanelOwnership";
import { MODEL_LOADING_LABEL } from "@/components/chat/StatusPill";
import { readSettledDetail, schedulePersistSettledDetail } from "@/lib/webState";
import {
  chatMessagesFromHistory,
  forkInfoFromResponse,
  latestAssistantContentLength,
  type ChatForkInfo,
} from "./chatSessionControllerHelpers";

import { ReadOwner, isAbortError } from "@/lib/readOwner";

const HISTORY_PAGE = 50;
const RECOVERY_ERROR = "Unable to reconcile conversation. Reconnecting…";

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
  owner: ChatPanelOwner;
  onSessionAdopt: (request: OwnedSessionAdoption) => boolean;
  onSessionUpdated?: (id: string) => void;
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
  appendRecoveredStaleTurnNoteRef,
  owner,
  onSessionAdopt,
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
  const [recoverySnapshot, setRecoverySnapshot] = useState<ChatRecoveryResponse | null>(null);
  const [recoveryPollCount, setRecoveryPollCount] = useState(0);
  const [recoveryFailed, setRecoveryFailed] = useState(false);

  const activeSessionRef = useRef<string | null>(sessionId);
  const activeSessionAliasesRef = useRef<Set<string>>(new Set(sessionId ? [sessionId] : []));
  const sessionRecoverySeqRef = useRef(0);
  const activeTurnSessionIdRef = useRef<string | null>(null);
  const streamTextCharsRef = useRef(0);
  const prependScrollAnchorRef = useRef<ChatPrependScrollAnchor | null>(null);
  const resyncInFlightRef = useRef<number | null>(null);
  const warmedRecoverySeqRef = useRef<number | null>(null);
  const exactAssistantContentRef = useRef<Map<string, string>>(new Map());
  const exactSearchRequestKeyRef = useRef("");
  const onSessionUpdatedRef = useRef(onSessionUpdated);
  const mountedRef = useRef(true);
  const timersRef = useRef(new Set<number>());
  useEffect(() => {
    mountedRef.current = true;
    const timers = timersRef.current;
    return () => {
      mountedRef.current = false;
      sessionRecoverySeqRef.current += 1;
      timers.forEach((timer) => window.clearTimeout(timer));
      timers.clear();
    };
  }, []);
  const isOwnerCurrent = useCallback(() => mountedRef.current && owner.isCurrent() && isChatPanelScopeCurrent(owner), [owner]);
  const messageAnchor = useMessageAnchor(sessionId, isOwnerCurrent);
  const readOwnerRef = useRef<ReadOwner | null>(null);
  useEffect(() => {
    const reads = new ReadOwner(isOwnerCurrent);
    readOwnerRef.current = reads;
    return () => {
      reads.retire();
      if (readOwnerRef.current === reads) readOwnerRef.current = null;
    };
  }, [isOwnerCurrent, sessionId]);
  const read = useCallback(<T,>(request: (signal: AbortSignal) => Promise<T>): Promise<T> => {
    if (!isOwnerCurrent() || !readOwnerRef.current) return Promise.reject(new DOMException("Read owner retired", "AbortError"));
    return readOwnerRef.current.read(request);
  }, [isOwnerCurrent]);
  const schedule = useCallback((callback: () => void, delay: number) => {
    if (!isOwnerCurrent()) return;
    const timer = window.setTimeout(() => {
      timersRef.current.delete(timer);
      if (isOwnerCurrent()) callback();
    }, delay);
    timersRef.current.add(timer);
  }, [isOwnerCurrent]);

  onSessionUpdatedRef.current = onSessionUpdated;
  if (activeSessionRef.current !== activeSessionId) {
    activeSessionRef.current = activeSessionId;
    activeSessionAliasesRef.current = new Set(activeSessionId ? [activeSessionId] : []);
  } else if (activeSessionId) {
    activeSessionAliasesRef.current.add(activeSessionId);
  }

  const rememberActiveSessionAliases = useCallback((...ids: Array<string | null | undefined>) => {
    ids.forEach((id) => {
      if (id) activeSessionAliasesRef.current.add(id);
    });
  }, []);

  const resetActiveSessionAliases = useCallback((...ids: Array<string | null | undefined>) => {
    activeSessionAliasesRef.current = new Set(ids.filter((id): id is string => Boolean(id)));
  }, []);

  const isCurrentSessionResponse = useCallback((recoverySequence: number, ...ids: Array<string | null | undefined>) => (
    isOwnerCurrent() && isCurrentSessionResponseFor(
      recoverySequence,
      sessionRecoverySeqRef.current,
      activeSessionRef.current,
      activeSessionAliasesRef.current,
      ...ids,
    )
  ), [isOwnerCurrent]);

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
    const response = await read((signal) => api.getSessionMessages(requestedSessionId, HISTORY_PAGE, undefined, signal));
    mergeHistoryResponse(response, requestedSessionId, recoverySequence, options);
    return response;
  }, [mergeHistoryResponse, read]);

  const refreshLatestTranscript = useCallback(async (options: {
    sessionId?: string;
    persistSequence?: number;
    syncTail?: boolean;
  } = {}) => {
    const requestedSessionId = options.sessionId ?? activeSessionRef.current;
    if (!requestedSessionId || !isOwnerCurrent()) return null;
    const recoverySequence = sessionRecoverySeqRef.current;
    setLoadingHistory(true);
    try {
      const response = await loadHistoryPage(requestedSessionId, recoverySequence, {
        preferSyncedAssistants: true,
      });
      if (!isCurrentSessionResponse(recoverySequence, requestedSessionId, response.session_id)) return null;
      if (options.persistSequence !== undefined) {
        schedulePersistSettledDetail(
          response.session_id ?? requestedSessionId,
          response.messages,
          options.persistSequence,
          true,
        );
      }
      if (options.syncTail) {
        schedule(() => {
          void read((signal) => api.getSessionMessages(requestedSessionId, 20, undefined, signal)).then((tailResponse) => {
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
    } catch (error) {
      if (isAbortError(error) || !isCurrentSessionResponse(recoverySequence, requestedSessionId)) return null;
      throw error;
    } finally {
      if (isCurrentSessionResponse(recoverySequence, requestedSessionId)) setLoadingHistory(false);
    }
  }, [isCurrentSessionResponse, isOwnerCurrent, loadHistoryPage, read, rememberActiveSessionAliases, schedule]);

  const resyncTurnState = useCallback(async (options: { allowIdle?: boolean } = {}) => {
    const sid = activeSessionRef.current;
    if (!sid || !isOwnerCurrent() || (!streamingRef.current && !options.allowIdle) || resyncInFlightRef.current === sessionRecoverySeqRef.current) return;
    const recoverySequence = sessionRecoverySeqRef.current;
    resyncInFlightRef.current = recoverySequence;
    setRecoveryPollCount((count) => count + 1);
    recordWebEfficiency("httpPolls");
    recordWebEfficiency("streamRecoveryActions");
    try {
      const snapshot = await read((signal) => api.getChatRecovery(sid, undefined, signal));
      if (!isCurrentSessionResponse(recoverySequence, sid)) return;
      if (!isAuthoritativeRecoveryFor(snapshot, sid)) throw new Error("Recovery needs reconciliation");
      setError((previous) => previous === RECOVERY_ERROR ? null : previous);
      setRecoveryFailed(false);
      setRecoverySnapshot(snapshot);
      if (warmedRecoverySeqRef.current !== recoverySequence) {
        warmedRecoverySeqRef.current = recoverySequence;
        schedule(() => {
          if (isCurrentSessionResponse(recoverySequence, sid)) void api.warmSession(snapshot.latest_session_id).catch(() => {});
        }, 400);
      }
      rememberActiveSessionAliases(sid, ...snapshot.lineage);
      activeTurnSessionIdRef.current = snapshot.active_turn_session_id;
      setTurnState(recoverTurnStateFromBackend({
        turnActive: snapshot.turn_active, phase: snapshot.phase, state: snapshot.state,
        interruptRequested: snapshot.interrupt_requested,
      }));
      setStatusLabel(backendTurnStatusLabel({
        turnActive: snapshot.turn_active, phase: snapshot.phase, state: snapshot.state,
        status: snapshot.status, idleForSeconds: snapshot.idle_for_seconds,
      }));
      if (snapshot.turn_active) {
        setStreaming(true);
      } else {
        flushPendingStreamRef.current?.();
        finalizeAssistantRef.current?.();
        setStreaming(false);
      }
      mergeHistoryResponse(snapshot.history, sid, recoverySequence, {
        preferSyncedAssistants: !snapshot.turn_active,
        preserveLocalAssistantPrefix: snapshot.turn_active,
      });
      // A complete saved-history replacement must not erase this recovery label.
      if (!snapshot.turn_active && snapshot.stream_text_mode === "unknown") appendRecoveredStaleTurnNoteRef.current?.(
        "The live response is unavailable after a restart. Saved history is shown; work has not been replayed.",
      );
    } catch (error) {
      if (!isAbortError(error) && isCurrentSessionResponse(recoverySequence, sid)) {
        setRecoveryFailed(true);
        setError(RECOVERY_ERROR);
      }
    } finally {
      if (isCurrentSessionResponse(recoverySequence, sid) && resyncInFlightRef.current === recoverySequence) resyncInFlightRef.current = null;
    }
  }, [
    appendRecoveredStaleTurnNoteRef,
    finalizeAssistantRef,
    flushPendingStreamRef,
    isCurrentSessionResponse,
    isOwnerCurrent,
    mergeHistoryResponse,
    read,
    schedule,
    rememberActiveSessionAliases,
    setStreaming,
    setTurnState,
    streamingRef,
  ]);

  useEffect(() => {
    // A proxy can keep EventSource open across backend loss. Retain the
    // existing two-second reconciliation cadence only for confirmed stalled
    // work (or a failed read), using the same single-response recovery path.
    // Healthy navigation/reconnect still consumes one request. Never replay work.
    if (!recoveryFailed && !(recoverySnapshot?.turn_active && recoverySnapshot.state === "stalled")) return;
    const recoverySequence = sessionRecoverySeqRef.current;
    const timer = window.setInterval(() => {
      if (recoverySequence === sessionRecoverySeqRef.current) void resyncTurnState({ allowIdle: true });
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [recoveryFailed, recoverySnapshot, resyncTurnState]);

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
    setLoadingEarlier(false);
    resyncInFlightRef.current = null;
    setSessionStats({});
    setForkInfo(null);
    setRecoverySnapshot(null);
    setRecoveryFailed(false);
    activeTurnSessionIdRef.current = null;
    streamTextCharsRef.current = 0;
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

    // Keep this owner's cached transcript visible while authoritative state
    // reconciles. Hiding it behind a skeleton adds a round trip to warm opens.
    setLoadingHistory(initialTranscript.length === 0);
    void resyncTurnState({ allowIdle: true }).finally(() => {
      if (recoveryStillCurrent()) setLoadingHistory(false);
    });
    void read((signal) => api.getSessionForks(sessionId, signal)).then((info) => {
      if (recoveryStillCurrent()) setForkInfo(forkInfoFromResponse(info));
    }).catch(() => {});

    return () => {
      cancelled = true;
    };
    // Session changes intentionally start a new guarded request sequence.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const doFork = useCallback(async (fromSessionIdx?: number) => {
    const sid = activeSessionRef.current;
    const request = owner.beginRequest();
    if (!sid || !request || !isOwnerCurrent()) return;
    try {
      const result = await api.forkConversation(sid, fromSessionIdx);
      if (!isOwnerCurrent()) return;
      onSessionAdopt({ ...request, nextID: result.session_id, reason: "fork" });
    } catch (err) {
      if (isOwnerCurrent()) setError(err instanceof Error ? err.message : String(err));
    }
  }, [isOwnerCurrent, onSessionAdopt, owner]);

  const doRetry = useCallback(async (messageIndex: number, edited?: string) => {
    const sid = activeSessionRef.current;
    const recoverySequence = sessionRecoverySeqRef.current;
    if (!sid || !isOwnerCurrent() || streamingRef.current) return;
    try {
      await api.retryConversation(sid, messageIndex, edited);
      if (!isCurrentSessionResponse(recoverySequence, sid)) return;
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
      if (isCurrentSessionResponse(recoverySequence, sid)) setError(err instanceof Error ? err.message : String(err));
    }
  }, [isCurrentSessionResponse, isOwnerCurrent, setStreaming, setTurnState, streamingRef]);

  const loadEarlierMessages = useCallback(async () => {
    if (!isOwnerCurrent()) return;
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
      const response = await read((signal) => api.getSessionMessages(request.sessionId, request.limit, request.beforeId, signal));
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
      if (isCurrentSessionResponse(recoverySequence, request.sessionId)) prependScrollAnchorRef.current = null;
    } finally {
      if (isCurrentSessionResponse(recoverySequence, request.sessionId)) setLoadingEarlier(false);
    }
  }, [chatMessages, isCurrentSessionResponse, isOwnerCurrent, loadingEarlier, read, rememberActiveSessionAliases, scrollContainerRef]);

  const loadExactMessages = useCallback(async () => {
    // Exact-content reads belong to this view too; retirement cancels the read
    // without cancelling any already accepted promotion or other mutation.
    const sid = activeSessionId;
    if (!sid) return [] as SessionMessage[];
    if (!isChatPanelScopeCurrent(owner)) throw new Error("The chat backend or profile changed.");
    const response = await read((signal) => api.getSessionMessages(sid, 0, undefined, signal));
    if (!isChatPanelScopeCurrent(owner)) throw new Error("The chat backend or profile changed.");
    for (const message of isOwnerCurrent() ? response.messages : []) {
      if (message.role === "assistant" && message.id != null && message.content != null) {
        exactAssistantContentRef.current.set(`db:${message.id}`, message.content);
      }
    }
    return response.messages;
  }, [activeSessionId, isOwnerCurrent, owner, read]);

  const fetchExactAssistant = useCallback(async (
    message: Extract<ChatMessage, { role: "assistant" }>,
  ) => {
    if (!isChatPanelScopeCurrent(owner)) throw new Error("The chat backend or profile changed.");
    if (!message.liveOmittedChars) return message.content;
    const cached = exactAssistantContentRef.current.get(message.id);
    if (cached != null) return cached;
    const messages = await loadExactMessages();
    const exact = exactAssistantContent(messages, message.id) ?? message.content;
    if (isOwnerCurrent()) exactAssistantContentRef.current.set(message.id, exact);
    return exact;
  }, [isOwnerCurrent, loadExactMessages, owner]);

  return {
    messageAnchor,
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
    recoverySnapshot,
    recoveryFailed,
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
