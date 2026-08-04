import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ChevronLeft,
  X,
  Loader2,
  GitFork,
  RotateCcw,
  Copy,
  Search,
  ChevronUp,
  ChevronDown,
  CornerUpLeft,
  ShieldCheck,
  Activity,
  RefreshCw,
  PlayCircle,
} from "lucide-react";
// Square/Send/handleKeyDown removed — now handled by PromptBar
import { api, type SubagentRun, type WebPendingAction, type WebPlan, type WebTurnOutcome } from "@/lib/api";
import { cn } from "@/lib/utils";
import { BrandLogo } from "@/components/BrandLogo";
import { Button } from "@/components/ui/button";
import {
  useEventBus,
  useSelectedDetailSubscription,
} from "@/hooks/useEventBus";
import { estimateAssistantRowSize } from "@/lib/rowMeasurement";
import { MODEL_LOADING_LABEL, StatusPill } from "@/components/chat/StatusPill";
import { PromptBar } from "@/components/chat/PromptBar";
import { ContextTray } from "@/components/chat/ContextTray";
import { BriefPanel } from "@/components/chat/BriefPanel";
import { SessionInfoBar } from "@/components/chat/SessionInfoBar";
import { TimelineMinimap } from "@/components/chat/TimelineMinimap";
import { TimelineTurnGroup } from "@/components/chat/MessagesTimeline";
import { ChangedFilesCard } from "@/components/chat/ChangedFilesCard";
import { PlanCard } from "@/components/chat/PlanCard";
import { PendingActionTray } from "@/components/chat/PendingActionTray";
import { MessageRowSkeleton } from "@/components/Skeleton";
import { setTrayStatus } from "@/lib/desktop";
import { makeFileContextItem, briefApi } from "@/lib/context";
import type { ContextItem, InclusionMode, ContextScope } from "@/lib/context";
import {
  nextChatTurnState,
  type ChatTurnState,
} from "@/lib/chatTurnState";
import { consumeRecoverySignal, initialRecoverySignalBudget } from "@/lib/chatRecovery";
import {
  recoveryActionsForTurn,
  readChatDiagnosticCounters,
  safeDiagnosticsJson,
  type RecoveryActionId,
} from "@/lib/chatDiagnostics";
import {
  persistSafeMode,
  pruneLongTasks,
  readSafeMode,
  rememberRenderHealth,
  shouldEnableSafeMode,
  type LongTaskSample,
} from "@/lib/renderHealth";
import {
  initialChatScrollState,
  reduceChatScrollState,
  shouldAutoScrollChat,
} from "@/lib/chatScrollState";
import {
  rememberLocalTurn,
  type ChatMessage,
} from "@/lib/chatTranscriptMerge";
import {
  approvalFailureMessage,
  approvalSubmission,
} from "@/lib/chatApproval";
import {
  streamingAssistantVisibleChars as getStreamingAssistantVisibleChars,
} from "@/lib/chatTimeline";
import {
  buildThreadTimeline,
  type ThreadTimeline,
  type ThreadTimelineMessage,
} from "@/lib/threadTimelineModel";
import { outcomeForTimelineTurn } from "@/lib/turnOutcomeModel";
import { buildTurnLandmarks } from "@/components/chat/timelineMinimapModel";
import { copyExactAssistantContent } from "@/lib/exactMessage";
import { recordWebEfficiency } from "@/lib/efficiencyMetrics";
import { clearUnsettledOrInvalidDetailCache } from "@/lib/webState";
import { useChatSessionController, type ChatSessionResetInput } from "@/hooks/useChatSessionController";
import { useChatComposerActions } from "@/hooks/useChatComposerActions";
import { useChatStreamController } from "@/hooks/useChatStreamController";
import type { ChatStreamSnapshot } from "@/lib/chatStreamReducer";

let _msgId = 0;
const nid = () => `m${++_msgId}`;
const CHAT_WORD_WRAP_CHANGED_EVENT = "spark:chat-word-wrap-changed";

const chatWordWrapFromConfig = (config: Record<string, unknown>): boolean => {
  const display = config.display;
  return Boolean(
    display &&
      typeof display === "object" &&
      (display as Record<string, unknown>).chat_word_wrap,
  );
};

interface ChatPanelProps {
  sessionId: string | null;
  onClose?: () => void;
  onBack?: () => void;
  onSessionCreated?: (
    id: string,
    initialMessage?: string,
    meta?: { source?: string | null; projectSlug?: string | null },
  ) => void;
  onSessionUpdated?: (id: string) => void;
  sessionTitle?: string | null;
  initialMessage?: string;
  workspaceSlug?: string;
  subagents?: SubagentRun[];
  onSubagentSelect?: (subagentId: string) => void;
  className?: string;
}

function SparkAgentIcon({ className = "h-4 w-4" }: { className?: string }) {
  return <BrandLogo className={className} />;
}

type AssistantMsg = Extract<ChatMessage, { role: "assistant" }>;
// ── ChatPanel ─────────────────────────────────────────────────────────────────

export function ChatPanel({
  sessionId,
  onClose,
  onBack,
  onSessionCreated,
  onSessionUpdated,
  initialMessage,
  workspaceSlug,
  subagents = [],
  onSubagentSelect,
  className,
}: ChatPanelProps) {
  useSelectedDetailSubscription(sessionId);
  useEffect(() => {
    recordWebEfficiency("reactCommits");
  });
  const [input, setInput] = useState(() => {
    // First-run "try this" prompt seeded by onboarding — pre-fill once.
    try {
      const starter = localStorage.getItem("spark-starter-prompt");
      if (starter) {
        localStorage.removeItem("spark-starter-prompt");
        return starter;
      }
    } catch {
      /* ignore */
    }
    return "";
  });
  const [contextItems, setContextItems] = useState<ContextItem[]>([]);
  const [turnState, setTurnState] = useState<ChatTurnState>("idle");
  const streaming = turnState !== "idle";
  const setStreaming = useCallback((active: boolean) => {
    setTurnState(active ? "streaming" : "idle");
  }, []);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const approvalBusyRef = useRef(false);
  const [turnOutcomes, setTurnOutcomes] = useState<WebTurnOutcome[]>([]);
  const [conversationPlan, setConversationPlan] = useState<WebPlan | null>(null);
  const [pendingActions, setPendingActions] = useState<WebPendingAction[]>([]);
  const [confirmedTurnStatus, setConfirmedTurnStatus] = useState<Awaited<ReturnType<typeof api.getTurnStatus>> | null>(null);
  const turnSurfaceRefreshGenerationRef = useRef(0);
  const [busyActionIds, setBusyActionIds] = useState<Set<string>>(() => new Set());
  const [editingUser, setEditingUser] = useState<{ sessionIdx: number; text: string } | null>(null);
  const [safeMode, setSafeMode] = useState(() => readSafeMode(sessionId));
  const [safeModeNotice, setSafeModeNotice] = useState<string | null>(null);
  const [chatWordWrap, setChatWordWrap] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [conversationDiagnostics, setConversationDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [recoveryActionBusy, setRecoveryActionBusy] = useState<RecoveryActionId | null>(null);
  const [sseReconnectCount, setSseReconnectCount] = useState(0);

  useEffect(() => clearUnsettledOrInvalidDetailCache(), []);

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const scrollViewportTopRef = useRef<number | null>(null);

  useLayoutEffect(() => {
    const element = scrollContainerRef.current;
    if (!element) return;
    const nextTop = element.getBoundingClientRect().top;
    const previousTop = scrollViewportTopRef.current;
    if (previousTop != null && scrollStateRef.current.mode !== "following") {
      element.scrollTop += nextTop - previousTop;
    }
    scrollViewportTopRef.current = nextTop;
  }, [safeMode]);
  const streamingRef = useRef(false);
  const turnStateRef = useRef<ChatTurnState>("idle");
  const safeModeRef = useRef(safeMode);
  const onSessionResetRef = useRef<((input: ChatSessionResetInput) => void) | null>(null);
  const flushPendingStreamRef = useRef<(() => void) | null>(null);
  const finalizeAssistantRef = useRef<(() => void) | null>(null);
  const syncLiveAssistantSnapshotRef = useRef<((text: string, revision: number, start: number) => void) | null>(null);
  const appendRecoveredStaleTurnNoteRef = useRef<((text: string) => void) | null>(null);

  const controller = useChatSessionController({
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
    onSessionCreated: (id) => onSessionCreated?.(id),
    onSessionUpdated,
  });
  const {
    chatMessages,
    setChatMessages,
    activeSessionId,
    setActiveSessionId,
    loadingHistory,
    hasEarlier,
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
  } = controller;

  const recoverySignalBudgetRef = useRef(initialRecoverySignalBudget());
  const resyncTurnStateRef = useRef<((options?: { allowIdle?: boolean }) => Promise<void>) | null>(null);
  const lastPresentedStreamMessagesRef = useRef<readonly ChatMessage[] | null>(null);
  const lastHistoryMessagesRef = useRef<readonly ChatMessage[] | null>(null);
  const pendingStreamProjectionRef = useRef<readonly ChatMessage[] | null>(null);
  const streamStatusRef = useRef<string | null>(null);
  const streamTurnStateRef = useRef<string>("idle");
  const streamErrorRef = useRef<string | null>(null);
  // Keep the viewport pinned to the live tail while the user is following the
  // stream, but stop auto-scrolling as soon as they deliberately scroll upward.
  const followStreamRef = useRef(true);
  const scrollStateRef = useRef(initialChatScrollState());
  const prependRestoreGenerationRef = useRef(0);
  const [detachedFromBottom, setDetachedFromBottom] = useState(false);

  const handleStreamResync = useCallback((request: { reason: string; allowIdle: boolean }) => {
    if (request.reason === "reconnect") setSseReconnectCount((count) => count + 1);
    const result = consumeRecoverySignal(recoverySignalBudgetRef.current, Date.now());
    recoverySignalBudgetRef.current = result.budget;
    if (result.allowed) void resyncTurnState({ allowIdle: request.allowIdle });
  }, [resyncTurnState]);

  const handleStreamHistory = useCallback(async (request: {
    sessionId: string;
    recoverySequence: number;
    reason: "turn-done" | "failure" | "snapshot-finalized";
  }) => {
    if (request.recoverySequence !== sessionRecoverySeqRef.current) return;
    if (!isCurrentSessionResponse(request.recoverySequence, request.sessionId)) return;
    await refreshLatestTranscript({
      sessionId: request.sessionId,
      syncTail: request.reason === "turn-done",
    });
  }, [isCurrentSessionResponse, refreshLatestTranscript, sessionRecoverySeqRef]);

  const streamController = useChatStreamController({
    activeSessionId,
    recoverySequence: sessionRecoverySeqRef.current,
    sessionAliases: [...activeSessionAliasesRef.current],
    initialMessages: chatMessages,
    callbacks: {
      onStateChange: (transition) => {
        const transitionSessionId = transition.state.activeSessionId;
        if (
          transitionSessionId
          && transitionSessionId !== activeSessionRef.current
          && !activeSessionAliasesRef.current.has(transitionSessionId)
        ) {
          return;
        }
        const nextMessages = transition.state.messages;
        if (lastPresentedStreamMessagesRef.current === nextMessages) return;
        lastPresentedStreamMessagesRef.current = nextMessages;
        const projection = [...nextMessages];
        pendingStreamProjectionRef.current = projection;
        setChatMessages(projection);
      },
      onFlushStream: () => flushPendingStreamRef.current?.(),
      onResync: handleStreamResync,
      onLoadHistory: handleStreamHistory,
      onEffectError: (effectError) => setError(effectError instanceof Error ? effectError.message : String(effectError)),
    },
  });
  const syncStreamMessages = streamController.syncMessages;

  const bridgeStreamSnapshot = useCallback((snapshot: ChatStreamSnapshot) => {
    streamController.applySnapshot(snapshot);
  }, [streamController]);

  flushPendingStreamRef.current = () => streamController.flush();
  finalizeAssistantRef.current = () => streamController.finalize();
  syncLiveAssistantSnapshotRef.current = (text, revision, start) => {
    const sid = activeSessionRef.current;
    if (!sid || !text) return;
    bridgeStreamSnapshot({
      session_id: sid,
      resolved_session_id: sid,
      active_turn_session_id: activeTurnSessionIdRef.current ?? sid,
      turn_active: true,
      stream_text: text,
      stream_revision: revision,
      stream_text_start: start,
      stream_text_chars: start + text.length,
    });
  };

  const composerActions = useChatComposerActions({
    input,
    contextItems,
    transcript: chatMessages,
    activeSessionId,
    activeTurnSessionIdRef,
    activeSessionRef,
    rememberActiveSessionAliases,
    turnState,
    turnStateRef,
    statusLabel,
    workspaceSlug,
    setInput,
    setContextItems,
    setChatMessages,
    setActiveSessionId,
    setTurnState,
    setStatusLabel,
    setError,
    createMessageId: nid,
    onSessionCreated,
    onPrepareSend: (optimisticMessageCount) => {
      followStreamRef.current = true;
      streamTextCharsRef.current = 0;
      scrollStateRef.current = reduceChatScrollState(scrollStateRef.current, {
        type: "jump-to-bottom",
        itemCount: optimisticMessageCount,
      });
      setDetachedFromBottom(false);
    },
    onEdit: (messageIndex, text) => setEditingUser({ sessionIdx: messageIndex, text }),
    retryAction: doRetry,
    forkAction: doFork,
    resyncTurnState,
  });
  const {
    sendMessage,
    stop,
    retryMessage,
    editMessage,
    forkMessage,
    forkSession,
  } = composerActions;

  streamingRef.current = streaming;
  turnStateRef.current = turnState;
  safeModeRef.current = safeMode;

  const appendRecoveredStaleTurnNote = useCallback((text: string) => {
    setChatMessages((prev) => {
      if (prev.some((m) => m.role === "note" && m.text === text)) return prev;
      return [...prev, { id: nid(), role: "note", text }];
    });
  }, [setChatMessages]);

  const latestUserMessage = useMemo(() => {
    return [...chatMessages]
      .reverse()
      .find((m): m is Extract<ChatMessage, { role: "user" }> =>
        m.role === "user" && typeof m.sessionIdx === "number",
      ) ?? null;
  }, [chatMessages]);

  const hasAssistantOutput = useMemo(() => (
    chatMessages.some((m) => m.role === "assistant" && m.content.trim().length > 0)
  ), [chatMessages]);

  useEffect(() => {
    let cancelled = false;
    void api.getConfig()
      .then((config) => {
        if (!cancelled) setChatWordWrap(chatWordWrapFromConfig(config));
      })
      .catch(() => {});
    const handleWrapChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ enabled?: unknown }>).detail;
      if (typeof detail?.enabled === "boolean") {
        setChatWordWrap(detail.enabled);
      }
    };
    window.addEventListener(CHAT_WORD_WRAP_CHANGED_EVENT, handleWrapChanged);
    return () => {
      cancelled = true;
      window.removeEventListener(CHAT_WORD_WRAP_CHANGED_EVENT, handleWrapChanged);
    };
  }, [activeSessionRef, setChatMessages]);

  // Desktop (§3.1): reflect agent activity in the menu-bar tray indicator.
  useEffect(() => {
    void setTrayStatus(streaming, streaming ? "Spark — working…" : undefined);
  }, [streaming]);

  useEffect(() => {
    rememberLocalTurn(activeSessionId, chatMessages);
  }, [activeSessionId, chatMessages]);

  useEffect(() => {
    rememberRenderHealth(activeSessionId, safeMode);
  }, [activeSessionId, safeMode]);

  const enableSafeMode = useCallback((reason: string, longTaskCount = 0) => {
    const sid = activeSessionRef.current;
    if (!sid || safeModeRef.current) return;
    persistSafeMode(sid, true);
    safeModeRef.current = true;
    setSafeMode(true);
    setSafeModeNotice(reason);
    rememberRenderHealth(sid, true, longTaskCount);
    setChatMessages((prev) => [
      ...prev,
      { id: nid(), role: "note", text: reason },
    ]);
  }, [activeSessionRef, setChatMessages]);

  const disableSafeMode = useCallback(() => {
    const sid = activeSessionRef.current;
    persistSafeMode(sid, false);
    safeModeRef.current = false;
    setSafeMode(false);
    setSafeModeNotice(null);
    rememberRenderHealth(sid, false);
  }, [activeSessionRef]);

  useEffect(() => {
    if (typeof PerformanceObserver === "undefined") return;
    if (!PerformanceObserver.supportedEntryTypes?.includes("longtask")) return;

    let recent: LongTaskSample[] = [];
    const WINDOW_MS = 12_000;
    const TRIGGER_COUNT = 4;
    const TRIGGER_DURATION_MS = 250;

    let observer: PerformanceObserver;
    try {
      observer = new PerformanceObserver((list) => {
        const now = performance.now();
        for (const entry of list.getEntries()) {
          recent.push({ start: entry.startTime, duration: entry.duration });
        }
        recent = pruneLongTasks(recent, now, WINDOW_MS);
        if (
          shouldEnableSafeMode(recent, {
            streaming: streamingRef.current,
            triggerCount: TRIGGER_COUNT,
            triggerDurationMs: TRIGGER_DURATION_MS,
          })
        ) {
          enableSafeMode("Safe render mode turned on for this thread after repeated browser long tasks.", recent.length);
        }
      });
      observer.observe({ type: "longtask", buffered: false });
    } catch {
      return;
    }
    return () => observer.disconnect();
  }, [enableSafeMode]);

  appendRecoveredStaleTurnNoteRef.current = appendRecoveredStaleTurnNote;
  resyncTurnStateRef.current = resyncTurnState;
  onSessionResetRef.current = ({
    sessionId: resetSessionId,
    initialTranscript,
    initialMessage: resetInitialMessage,
    recoverySequence,
  }) => {
    // Drop all bridge identities from the previous session before installing
    // the new reducer source. Otherwise a late old projection can be mistaken
    // for the selected session's initial transcript.
    lastPresentedStreamMessagesRef.current = null;
    lastHistoryMessagesRef.current = null;
    pendingStreamProjectionRef.current = null;
    activeSessionRef.current = resetSessionId;
    prependRestoreGenerationRef.current += 1;
    const transition = streamController.setSession({
      sessionId: resetSessionId,
      aliases: resetSessionId ? [resetSessionId] : [],
      recoverySequence,
      messages: initialTranscript,
    });
    streamStatusRef.current = transition.state.statusLabel;
    streamTurnStateRef.current = transition.state.turnState;
    streamErrorRef.current = transition.state.error;
    prependScrollAnchorRef.current = null;
    recoverySignalBudgetRef.current = initialRecoverySignalBudget();
    prevCountRef.current = 0;
    lastAutoScrollAtRef.current = 0;
    scrollStateRef.current = reduceChatScrollState(initialChatScrollState(initialTranscript.length), {
      type: "jump-to-bottom",
      itemCount: initialTranscript.length,
    });
    setDetachedFromBottom(false);
    followStreamRef.current = true;
    setEditingUser(null);
    setDiagnosticsOpen(false);
    setConversationDiagnostics(null);
    setDiagnosticsError(null);
    const restoredSafeMode = readSafeMode(resetSessionId);
    setSafeMode(restoredSafeMode);
    setSafeModeNotice(restoredSafeMode ? "Recovered this thread in safe mode." : null);
    if (resetInitialMessage) {
      streamTurnStateRef.current = "starting";
      setTurnState("starting");
      setStatusLabel(MODEL_LOADING_LABEL);
    }
  };

  useEffect(() => {
    const pendingProjection = pendingStreamProjectionRef.current;
    if (pendingProjection === chatMessages) {
      pendingStreamProjectionRef.current = null;
      lastHistoryMessagesRef.current = chatMessages;
      return;
    }
    // A controller history response may land before the reducer projection
    // render that was queued by an earlier stream transition. In that case
    // the current controller array is the newer source; never echo the stale
    // projection back over it or leave the guard armed indefinitely.
    if (pendingProjection !== null) pendingStreamProjectionRef.current = null;
    if (chatMessages === lastHistoryMessagesRef.current) return;
    lastHistoryMessagesRef.current = chatMessages;
    syncStreamMessages(chatMessages);
  }, [chatMessages, syncStreamMessages]);

  useEffect(() => {
    const streamState = streamController.state;
    streamTextCharsRef.current = Math.max(streamTextCharsRef.current, streamState.streamTextChars);
    activeTurnSessionIdRef.current = streamState.activeTurnSessionId;

    if (
      streamState.recoverySequence === sessionRecoverySeqRef.current
      && streamState.activeSessionId
      && streamState.activeSessionId !== activeSessionRef.current
    ) {
      rememberActiveSessionAliases(...streamState.sessionAliases);
      activeSessionRef.current = streamState.activeSessionId;
      setActiveSessionId(streamState.activeSessionId);
      onSessionUpdated?.(streamState.activeSessionId);
    }

    if (streamStatusRef.current !== streamState.statusLabel) {
      streamStatusRef.current = streamState.statusLabel;
      setStatusLabel(streamState.statusLabel);
    }

    if (streamTurnStateRef.current !== streamState.turnState) {
      streamTurnStateRef.current = streamState.turnState;
      const nextState: ChatTurnState = streamState.turnState === "starting"
        ? "starting"
        : streamState.turnState === "stopping"
          ? "stopping"
          : streamState.turnState === "redirecting"
            ? "redirecting"
            : streamState.turnState === "stalled"
              ? "stalled"
              : streamState.turnState === "streaming"
                || streamState.turnState === "awaiting-approval"
                || streamState.turnState === "awaiting-input"
                ? "streaming"
                : "idle";
      turnStateRef.current = nextState;
      setTurnState(nextState);
      setStreaming(nextState !== "idle");
    }

    if (streamErrorRef.current !== streamState.error) {
      streamErrorRef.current = streamState.error;
      if (streamState.error) setError(streamState.error);
    }

    const stats = streamState.stats;
    if (stats.turnCount > 0 || stats.model || stats.costUsd > 0) {
      setSessionStats({
        model: stats.model,
        inputTokens: stats.inputTokens,
        outputTokens: stats.outputTokens,
        cacheReadTokens: stats.cacheReadTokens,
        cacheWriteTokens: stats.cacheWriteTokens,
        costUsd: stats.costUsd,
        turnCount: stats.turnCount,
      });
    }
  }, [
    onSessionUpdated,
    rememberActiveSessionAliases,
    setActiveSessionId,
    setError,
    setSessionStats,
    setStatusLabel,
    setStreaming,
    setTurnState,
    streamController.state,
    streamTextCharsRef,
    activeSessionRef,
    activeTurnSessionIdRef,
    sessionRecoverySeqRef,
  ]);

  useEventBus((env) => {
    if (
      env.topic.startsWith("chat.")
      && env.session_id
      && !activeSessionAliasesRef.current.has(env.session_id)
    ) {
      return;
    }
    streamController.handleEvent({
      topic: env.topic,
      session_id: env.session_id,
      sequence: env.sequence,
      data: env.data,
    });
  });

  const refreshTurnSurfaces = useCallback(async () => {
    const generation = ++turnSurfaceRefreshGenerationRef.current;
    const sid = activeSessionRef.current;
    if (!sid) {
      setTurnOutcomes([]);
      setConversationPlan(null);
      setPendingActions([]);
      return;
    }
    const [outcomeResult, planResult, actionsResult] = await Promise.allSettled([
      api.getConversationTurnOutcomes(sid),
      api.getConversationPlan(sid),
      api.getConversationPendingActions(sid),
    ]);
    if (activeSessionRef.current !== sid || generation !== turnSurfaceRefreshGenerationRef.current) return;
    if (outcomeResult.status === "fulfilled") setTurnOutcomes(outcomeResult.value.outcomes);
    if (planResult.status === "fulfilled") setConversationPlan(planResult.value.plan);
    if (actionsResult.status === "fulfilled") setPendingActions(actionsResult.value.actions);
  }, [activeSessionRef]);

  useEffect(() => {
    void refreshTurnSurfaces();
  }, [activeSessionId, refreshTurnSurfaces]);

  useEventBus((env) => {
    if (![
      "chat.turn_done",
      "chat.plan_updated",
      "chat.approval_requested",
      "chat.approval_resolved",
      "chat.input_requested",
      "chat.input_resolved",
    ].includes(env.topic)) return;
    const sid = activeSessionRef.current;
    if (!sid || (env.session_id && !activeSessionAliasesRef.current.has(env.session_id))) return;
    void refreshTurnSurfaces();
  });

  useEffect(() => {
    const sid = activeSessionId;
    let cancelled = false;
    setConfirmedTurnStatus(null);
    if (!sid) return;
    const refresh = async () => {
      try {
        const status = await api.getTurnStatus(sid);
        if (!cancelled && activeSessionRef.current === sid) setConfirmedTurnStatus(status);
      } catch {
        // Keep the last confirmed status; transport recovery owns user-facing
        // connectivity labels and a transient poll failure must not resurrect
        // stale optimistic state.
      }
    };
    void refresh();
    if (!streaming) return () => { cancelled = true; };
    const timer = window.setInterval(() => void refresh(), 2_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeSessionId, activeSessionRef, streaming]);
  const refreshConversationDiagnostics = useCallback(async () => {
    const sid = activeSessionRef.current;
    if (!sid) return null;
    try {
      const diag = await api.getConversationDiagnostics(sid);
      const enriched = {
        ...diag,
        browser: {
          sse_reconnect_count: sseReconnectCount,
          recovery_poll_count: recoveryPollCount,
          counters: readChatDiagnosticCounters(),
          turn_state: turnStateRef.current,
          streaming: streamingRef.current,
          safe_mode: safeModeRef.current,
        },
      };
      setConversationDiagnostics(enriched);
      setDiagnosticsError(null);
      return enriched;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setDiagnosticsError(msg);
      return null;
    }
  }, [activeSessionRef, recoveryPollCount, sseReconnectCount]);

  const continueFromSavedOutput = useCallback(async () => {
    const sid = activeSessionRef.current;
    if (!sid) return;
    const text = "Continue from the last saved assistant output.";
    setRecoveryActionBusy("continue");
    setError(null);
    try {
      if (streamingRef.current) {
        const activeSid = activeTurnSessionIdRef.current ?? sid;
        setChatMessages((prev) => [...prev, { id: nid(), role: "user", content: text, redirect: true }]);
        setTurnState(nextChatTurnState(turnStateRef.current, { type: "interrupt_requested", redirect: true }));
        setStatusLabel("Redirecting…");
        await api.interruptConversation(activeSid, text);
      } else {
        setChatMessages((prev) => [...prev, { id: nid(), role: "user", content: text }]);
        setTurnState(nextChatTurnState(turnStateRef.current, { type: "submit" }));
        setStatusLabel(MODEL_LOADING_LABEL);
        followStreamRef.current = true;
        streamTextCharsRef.current = 0;
        await api.postConversationMessage(sid, text);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      void resyncTurnStateRef.current?.({ allowIdle: true });
    } finally {
      setRecoveryActionBusy(null);
    }
  }, [
    activeSessionRef,
    activeTurnSessionIdRef,
    followStreamRef,
    resyncTurnStateRef,
    setChatMessages,
    setError,
    setStatusLabel,
    setTurnState,
    streamTextCharsRef,
    streamingRef,
  ]);

  const copyConversationDiagnostics = useCallback(async () => {
    setRecoveryActionBusy("copy");
    try {
      const diag = await refreshConversationDiagnostics();
      await navigator.clipboard.writeText(safeDiagnosticsJson(diag ?? conversationDiagnostics ?? {}));
      setStatusLabel("Diagnostics copied");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRecoveryActionBusy(null);
    }
  }, [conversationDiagnostics, refreshConversationDiagnostics, setError, setStatusLabel]);

  const runRecoveryAction = useCallback(async (id: RecoveryActionId) => {
    if (recoveryActionBusy) return;
    setRecoveryActionBusy(id);
    try {
      if (id === "reload") {
        await refreshLatestTranscript();
      } else if (id === "retry") {
        if (latestUserMessage?.sessionIdx != null) await retryMessage(latestUserMessage.sessionIdx);
      } else if (id === "stop") {
        await stop();
      } else if (id === "continue") {
        setRecoveryActionBusy(null);
        await continueFromSavedOutput();
        return;
      } else if (id === "copy") {
        setRecoveryActionBusy(null);
        await copyConversationDiagnostics();
        return;
      }
    } finally {
      setRecoveryActionBusy(null);
    }
  }, [
    copyConversationDiagnostics,
    continueFromSavedOutput,
    latestUserMessage,
    retryMessage,
    recoveryActionBusy,
    refreshLatestTranscript,
    stop,
  ]);

  const recoveryActions = useMemo(() => recoveryActionsForTurn({
    hasSession: Boolean(activeSessionId),
    turnState,
    streaming,
    hasLastUserMessage: Boolean(latestUserMessage),
    hasAssistantOutput,
    busy: recoveryActionBusy !== null,
  }), [
    activeSessionId,
    hasAssistantOutput,
    latestUserMessage,
    recoveryActionBusy,
    streaming,
    turnState,
  ]);

  // A stalled turn may show its compact warning and Diagnostics button, but
  // the full panel is controlled exclusively by that button.
  const shouldShowRecoveryPanel = Boolean(activeSessionId) && diagnosticsOpen;

  useEffect(() => {
    if (!shouldShowRecoveryPanel) return;
    void refreshConversationDiagnostics();
  }, [refreshConversationDiagnostics, shouldShowRecoveryPanel, turnState]);

  const submitApproval = useCallback(async (
    choice: "once" | "session" | "always" | "deny",
    actionId?: string,
  ) => {
    const sid = activeSessionRef.current;
    const submission = approvalSubmission({
      sessionId: sid,
      choice,
      busy: approvalBusy || approvalBusyRef.current,
    });
    if (!submission) return;
    approvalBusyRef.current = true;
    setApprovalBusy(true);
    try {
      await api.submitConversationApproval(
        submission.sessionId,
        submission.payload.choice,
        submission.payload.resolve_all,
        actionId,
      );
      await refreshTurnSurfaces();
    } catch (err) {
      setError(approvalFailureMessage(err));
    } finally {
      approvalBusyRef.current = false;
      setApprovalBusy(false);
    }
  }, [activeSessionRef, approvalBusy, refreshTurnSurfaces, setError]);

  const runPendingAction = useCallback(async (
    action: WebPendingAction,
    operation: () => Promise<unknown>,
  ) => {
    setBusyActionIds((current) => new Set(current).add(action.action_id));
    try {
      await operation();
      await refreshTurnSurfaces();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyActionIds((current) => {
        const next = new Set(current);
        next.delete(action.action_id);
        return next;
      });
    }
  }, [refreshTurnSurfaces, setError]);

  const copyText = useCallback((t: string) => {
    void navigator.clipboard.writeText(t);
  }, []);

  const copyAssistant = useCallback((msg: AssistantMsg) => {
    if (!msg.liveOmittedChars) {
      void navigator.clipboard.writeText(msg.content);
      return;
    }
    void copyExactAssistantContent({
      renderedId: msg.id,
      visibleFallback: msg.content,
      loadMessages: loadExactMessages,
      writeText: (content) => navigator.clipboard.writeText(content),
    })
      .catch(() => navigator.clipboard.writeText(msg.content));
  }, [loadExactMessages]);

  const uploadFiles = useCallback(async (files: File[]) => {
    const res = workspaceSlug
      ? await api.uploadWorkspaceFiles(workspaceSlug, files, "files")
      : await api.uploadChatFiles(files);
    for (const f of res.saved) {
      const path = "path" in f ? (f as { path: string }).path : `files/${f.filename}`;
      const sizeBytes = "size" in f ? (f as { size?: number }).size ?? 0 : 0;
      setContextItems((prev) => [...prev, makeFileContextItem(path, sizeBytes)]);
    }
  }, [workspaceSlug]);

  const attachPath = useCallback((path: string, sizeBytes = 0) => {
    setContextItems((prev) => {
      if (prev.some((i) => i.source_path === path)) return prev;
      return [...prev, makeFileContextItem(path, sizeBytes)];
    });
  }, []);

  const fetchFullToolResult = useCallback(async (toolId: string) => {
    const sid = activeSessionRef.current;
    if (!sid || !toolId) return null;
    const resp = await api.getSessionToolResult(sid, toolId);
    const content = resp.content ?? "";
    setChatMessages((prev) =>
      prev.map((m) =>
        m.role === "tool" && m.toolId === toolId
          ? { ...m, result: content, resultTruncated: false }
          : m,
      ),
    );
    return content;
  }, [activeSessionRef, setChatMessages]);

  const removeContextItem = useCallback((id: string) => {
    setContextItems((prev) => prev.filter((i) => i.id !== id));
  }, []);

  const updateContextMode = useCallback((id: string, mode: InclusionMode) => {
    setContextItems((prev) => prev.map((i) => i.id === id ? { ...i, inclusion_mode: mode } : i));
  }, []);

  const updateContextScope = useCallback((id: string, scope: ContextScope) => {
    setContextItems((prev) => prev.map((i) => i.id === id ? { ...i, scope } : i));
  }, []);

  const updateContextItem = useCallback((id: string, patch: Partial<ContextItem>) => {
    setContextItems((prev) => prev.map((i) => i.id === id ? { ...i, ...patch } : i));
  }, []);

  // Stable handlers passed to memoized row components
  const handleEdit = useCallback((idx: number) => {
    editMessage(idx);
  }, [editMessage]);
  const handleRetry = useCallback((idx: number) => { void retryMessage(idx); }, [retryMessage]);
  const handleFork = useCallback((idx: number) => { void forkMessage(idx); }, [forkMessage]);

  const summarizeContextItem = useCallback(async (id: string) => {
    const item = contextItems.find((i) => i.id === id);
    if (!item?.source_path) return;
    try {
      const res = await fetch("/api/summarize-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: item.source_path, workspace_slug: workspaceSlug }),
      });
      if (!res.ok) return;
      const { summary } = await res.json() as { summary: string };
      updateContextMode(id, "summary");
      setContextItems((prev) => prev.map((i) => i.id === id ? { ...i, content: summary, inclusion_mode: "summary" } : i));
    } catch {
      // silently ignore — user can retry
    }
  }, [contextItems, workspaceSlug, updateContextMode]);

  const handlePromoteToBrief = useCallback((msg: AssistantMsg) => {
    if (!activeSessionId) return;
    void fetchExactAssistant(msg).then((text) => briefApi.get(activeSessionId).then((r) => {
      const current = r.text.trim();
      const appended = current ? `${current}\n\n${text}` : text;
      return briefApi.set(activeSessionId, appended);
    })).catch(() => {});
  }, [activeSessionId, fetchExactAssistant]);

  // In-session search state
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchMatchIdx, setSearchMatchIdx] = useState(0);
  const exactSearchRequestKeyRef = useRef("");
  const searchInputRef = useRef<HTMLInputElement>(null);
  const messageListRef = useRef<HTMLDivElement>(null);

  // Cmd+F / Ctrl+F opens message search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        setSearchOpen((o) => {
          if (!o) setTimeout(() => searchInputRef.current?.focus(), 10);
          return !o;
        });
      }
      if (e.key === "Escape" && searchOpen) setSearchOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [searchOpen]);

  // Let other panels (e.g. the Changes tab's "Commit or push") drop a prompt
  // into the composer for the user to review and send — keeps the agent in the loop.
  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent<string>).detail;
      if (typeof text === "string" && text) setInput(text);
    };
    window.addEventListener("spark:compose", handler as EventListener);
    return () => window.removeEventListener("spark:compose", handler as EventListener);
  }, []);

  // Build match positions from messages — debounced so a streaming update at
  // 60fps doesn't trigger a full scan every frame when search is open.
  // searchQuery changes flush immediately; chatMessages changes are debounced 300ms.
  const [searchMatches, setSearchMatches] = useState<number[]>([]);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) { setSearchMatches([]); return; }
    const compute = () => {
      const results: number[] = [];
      chatMessages.forEach((msg, i) => {
        const text =
          msg.role === "user" || msg.role === "assistant"
            ? msg.content?.toLowerCase() ?? ""
            : msg.role === "reasoning"
            ? msg.text?.toLowerCase() ?? ""
            : "";
        if (text.includes(q)) results.push(i);
      });
      setSearchMatches(results);
    };
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(compute, 300);
    return () => {
      if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    };
  }, [chatMessages, searchQuery]);

  // Search exact oversized saved responses on demand without putting their
  // complete strings into React state or the rendered transcript.
  useEffect(() => {
    const q = searchQuery.trim().toLowerCase();
    const sid = activeSessionRef.current;
    const oversized = chatMessages.some(
      (msg) => msg.role === "assistant" && Boolean(msg.liveOmittedChars),
    );
    if (!q) exactSearchRequestKeyRef.current = "";
    if (!q || !sid || !oversized) return;
    const requestKey = `${sid}:${q}`;
    if (exactSearchRequestKeyRef.current === requestKey) return;
    exactSearchRequestKeyRef.current = requestKey;
    const recoverySeq = sessionRecoverySeqRef.current;
    let cancelled = false;
    void loadExactMessages().then(async () => {
      if (cancelled || recoverySeq !== sessionRecoverySeqRef.current) return;
      const results: number[] = [];
      for (const [index, msg] of chatMessages.entries()) {
        const text = msg.role === "assistant"
          ? await fetchExactAssistant(msg)
          : msg.role === "user" ? msg.content
          : msg.role === "reasoning" ? msg.text
          : "";
        if (text.toLowerCase().includes(q)) results.push(index);
      }
      setSearchMatches(results);
    }).catch(() => {
      if (exactSearchRequestKeyRef.current === requestKey) exactSearchRequestKeyRef.current = "";
    });
    return () => { cancelled = true; };
  }, [activeSessionRef, chatMessages, fetchExactAssistant, loadExactMessages, searchQuery, sessionRecoverySeqRef]);

  const turnIndexForMessageIndex = useCallback((messageIndex: number) => {
    let turnIndex = 0;
    for (let index = 0; index <= messageIndex && index < chatMessages.length; index += 1) {
      if (chatMessages[index]?.role === "user") turnIndex += 1;
    }
    return Math.max(0, turnIndex - 1);
  }, [chatMessages]);

  // Scroll active match into view using the virtualizer
  useEffect(() => {
    if (!searchMatches.length) return;
    const idx = turnIndexForMessageIndex(searchMatches[searchMatchIdx % searchMatches.length]);
    virtualizer.scrollToIndex(idx, { align: "center", behavior: safeMode ? "instant" : "smooth" });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchMatchIdx, searchMatches, safeMode, turnIndexForMessageIndex]);

  // Drag-and-drop state
  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounterRef = useRef(0);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (e.dataTransfer.types.includes("Files")) {
      dragCounterRef.current += 1;
      setIsDragOver(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dragCounterRef.current -= 1;
    if (dragCounterRef.current <= 0) {
      dragCounterRef.current = 0;
      setIsDragOver(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    dragCounterRef.current = 0;
    setIsDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) void uploadFiles(files);
  }, [uploadFiles]);

  const previousTimelineRef = useRef<ThreadTimeline | undefined>(undefined);
  const timelineSessionRef = useRef<string | null>(null);
  const threadTimeline = useMemo(() => {
    const sessionChanged = timelineSessionRef.current !== activeSessionId;
    const previous = sessionChanged ? undefined : previousTimelineRef.current;
    const messages = chatMessages as readonly ThreadTimelineMessage[];
    const projectedMessages = subagents.length > 0 && messages.length > 0
      ? messages.map((message, index) => index === messages.length - 1 ? {
          ...message,
          subagents: subagents.map((run) => ({
            id: run.id ?? run.run_id ?? run.subagent_id ?? "subagent",
            name: run.name ?? undefined,
            task: run.task ?? run.goal ?? undefined,
            status: run.status,
            error: run.error ?? undefined,
            startedAt: run.started_at ?? undefined,
            endedAt: run.ended_at ?? undefined,
          })),
        } : message)
      : messages;
    const next = buildThreadTimeline(projectedMessages, { previous });
    timelineSessionRef.current = activeSessionId;
    previousTimelineRef.current = next;
    return next;
  }, [activeSessionId, chatMessages, subagents]);
  const timelineTurns = threadTimeline.turns;

  const streamingAssistantVisibleChars = useMemo(
    () => getStreamingAssistantVisibleChars(chatMessages),
    [chatMessages],
  );

  const estimateRowSize = useCallback((index: number) => {
    const turn = timelineTurns[index];
    if (!turn) return 120;
    const answerChars = turn.finalAnswer?.content.length ?? 0;
    // estimateAssistantRowSize includes the standalone message-row chrome.
    // A timeline turn shares that chrome with its user row, so subtract the
    // duplicated allowance. Keeping the short-turn estimate close to its
    // rendered 90px height prevents late virtual-list remeasurement from
    // moving a preserved history anchor after prepending older messages.
    const answerEstimate = answerChars
      ? Math.max(36, estimateAssistantRowSize(turn.finalAnswer?.content ?? "") - 60)
      : 0;
    const expandedWorkEstimate = turn.isExpanded ? Math.min(720, turn.workItems.length * 64 + turn.subagents.length * 56) : 44;
    return Math.max(54, 54 + answerEstimate + (turn.workItems.length || turn.subagents.length ? expandedWorkEstimate : 0));
  }, [timelineTurns]);

  const virtualizer = useVirtualizer({
    count: timelineTurns.length,
    getScrollElement: () => scrollContainerRef.current,
    getItemKey: (index) => timelineTurns[index]?.id ?? index,
    estimateSize: estimateRowSize,
    overscan: safeMode ? 4 : 10,
    gap: 12,
  });
  const virtualOrderRef = useRef<{ sessionId: string | null; firstId: string | null; count: number }>({ sessionId: null, firstId: null, count: 0 });

  useLayoutEffect(() => {
    const firstId = timelineTurns[0]?.id ?? null;
    const previous = virtualOrderRef.current;
    virtualOrderRef.current = { sessionId: activeSessionId, firstId, count: timelineTurns.length };
    if (
      (previous.sessionId != null && previous.sessionId !== activeSessionId) ||
      (previous.firstId && firstId !== previous.firstId && timelineTurns.length > previous.count)
    ) {
      // A prepend moves stable keyed DOM rows to new virtual indexes. Reset the
      // index measurement cache before the anchor-restoration loop remeasures
      // mounted rows, otherwise stale starts can temporarily overlap rows.
      virtualizer.measure();
    }
  }, [activeSessionId, timelineTurns, virtualizer]);

  const rowResizeObserverRef = useRef<ResizeObserver | null>(null);
  const rowResizeRafRef = useRef<number | null>(null);

  const measureRowElement = useCallback((el: HTMLDivElement | null) => {
    if (!el) return;
    rowResizeObserverRef.current?.observe(el);
    virtualizer.measureElement(el);
  }, [virtualizer]);

  useEffect(() => {
    const root = messageListRef.current;
    if (!root || typeof ResizeObserver === "undefined") return;
    const measureRenderedRows = (entries?: ResizeObserverEntry[]) => {
      if (rowResizeRafRef.current !== null) cancelAnimationFrame(rowResizeRafRef.current);
      const rows = entries?.length
        ? entries
            .map((entry) => entry.target)
            .filter((target): target is HTMLDivElement => target instanceof HTMLDivElement)
        : Array.from(root.querySelectorAll<HTMLDivElement>("[data-index]"));
      rowResizeRafRef.current = requestAnimationFrame(() => {
        rowResizeRafRef.current = null;
        const scrollEl = scrollContainerRef.current;
        const anchorId = scrollStateRef.current.anchorId;
        const anchorBefore = anchorId && scrollEl
          ? Array.from(root.querySelectorAll<HTMLDivElement>("[data-row-id]"))
              .find((row) => row.dataset.rowId === anchorId)
              ?.getBoundingClientRect().top ?? null
          : null;
        rows.forEach((row) => measureRowElement(row));
        // While a bottom jump is in flight (session open / jump pill), row
        // measurement grows scrollHeight after the initial scrollToIndex —
        // re-clamp so the view never lands short of the latest message.
        if (scrollEl && scrollStateRef.current.mode === "jumping-to-bottom") {
          scrollEl.scrollTop = scrollEl.scrollHeight;
        }
        if (anchorBefore != null && scrollEl && anchorId) {
          requestAnimationFrame(() => {
            const anchorAfter = Array.from(root.querySelectorAll<HTMLDivElement>("[data-row-id]"))
              .find((row) => row.dataset.rowId === anchorId)
              ?.getBoundingClientRect().top;
            if (typeof anchorAfter === "number") {
              scrollEl.scrollTop += anchorAfter - anchorBefore;
            }
          });
        }
      });
    };
    const observer = new ResizeObserver((entries) => measureRenderedRows(entries));
    rowResizeObserverRef.current = observer;
    root
      .querySelectorAll<HTMLDivElement>("[data-index]")
      .forEach((row) => observer.observe(row));
    measureRenderedRows();
    return () => {
      observer.disconnect();
      if (rowResizeObserverRef.current === observer) {
        rowResizeObserverRef.current = null;
      }
      if (rowResizeRafRef.current !== null) {
        cancelAnimationFrame(rowResizeRafRef.current);
        rowResizeRafRef.current = null;
      }
    };
  }, [measureRowElement, timelineTurns]);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const updateFollowState = () => {
      if (loadingHistory || scrollStateRef.current.mode === "jumping-to-bottom") return;
      const firstVisibleIndex = virtualizer.getVirtualItems()[0]?.index;
      scrollStateRef.current = reduceChatScrollState(scrollStateRef.current, {
        type: "user-scroll",
        metrics: {
          scrollHeight: el.scrollHeight,
          scrollTop: el.scrollTop,
          clientHeight: el.clientHeight,
        },
        anchorId: firstVisibleIndex == null ? null : timelineTurns[firstVisibleIndex]?.id ?? null,
      });
      followStreamRef.current = scrollStateRef.current.mode === "following";
      setDetachedFromBottom(
        scrollStateRef.current.mode === "detached" ||
        scrollStateRef.current.mode === "pending-new-message",
      );
    };
    updateFollowState();
    el.addEventListener("scroll", updateFollowState, { passive: true });
    return () => el.removeEventListener("scroll", updateFollowState);
  }, [activeSessionId, loadingHistory, timelineTurns, virtualizer]);

  // Auto-scroll to bottom when new items arrive or streaming updates.
  // Use scrollContainerRef directly to avoid stacking rAFs.
  const prevCountRef = useRef(0);
  const autoScrollRafRef = useRef<number | null>(null);
  const lastAutoScrollAtRef = useRef(0);

  // Re-clamp to the bottom every frame until the virtualizer's measured size
  // stabilizes. A single scrollToIndex on session open uses estimated row
  // heights and lands short once rows are actually measured (scrollHeight
  // grows after the jump fired), so we only complete the jump when a frame
  // starts with the viewport already at the bottom (i.e. the previous clamp
  // survived remeasure).
  const bottomClampRafRef = useRef<number | null>(null);
  const runBottomClamp = useCallback(() => {
    if (bottomClampRafRef.current !== null) cancelAnimationFrame(bottomClampRafRef.current);
    let remaining = 30;
    let firstFrame = true;
    const step = () => {
      bottomClampRafRef.current = requestAnimationFrame(() => {
        bottomClampRafRef.current = null;
        const el = scrollContainerRef.current;
        if (!el || scrollStateRef.current.mode !== "jumping-to-bottom") return;
        const count = virtualizer.options.count;
        // Always clamp at least once; only settle when a frame starts with
        // the viewport already at the bottom (previous clamp survived any
        // row remeasure).
        if (!firstFrame) {
          scrollStateRef.current = reduceChatScrollState(scrollStateRef.current, {
            type: "jump-settle",
            itemCount: count,
            metrics: {
              scrollHeight: el.scrollHeight,
              scrollTop: el.scrollTop,
              clientHeight: el.clientHeight,
            },
          });
          if (scrollStateRef.current.mode !== "jumping-to-bottom") {
            followStreamRef.current = true;
            setDetachedFromBottom(false);
            return;
          }
        }
        firstFrame = false;
        if (count > 0) {
          virtualizer.scrollToIndex(count - 1, { align: "end", behavior: "instant" });
        }
        el.scrollTop = el.scrollHeight;
        lastAutoScrollAtRef.current = Date.now();
        remaining -= 1;
        if (remaining <= 0) {
          // Bail out rather than staying stuck in jumping mode forever.
          scrollStateRef.current = reduceChatScrollState(scrollStateRef.current, {
            type: "jump-complete",
            itemCount: count,
          });
          followStreamRef.current = true;
          setDetachedFromBottom(false);
          return;
        }
        step();
      });
    };
    step();
  }, [virtualizer]);

  useEffect(() => () => {
    if (bottomClampRafRef.current !== null) {
      cancelAnimationFrame(bottomClampRafRef.current);
      bottomClampRafRef.current = null;
    }
  }, []);

  // A session open always requests a bottom jump, but when a cached local
  // transcript already matches the loaded history no items-changed event
  // fires — so kick the clamp whenever history finishes loading (or the
  // active session changes) while a jump is still pending.
  useEffect(() => {
    if (!loadingHistory && scrollStateRef.current.mode === "jumping-to-bottom") {
      runBottomClamp();
    }
  }, [activeSessionId, loadingHistory, runBottomClamp]);
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const count = timelineTurns.length;
    const messageCount = chatMessages.length;
    const countChanged = count !== prevCountRef.current;
    const pendingPrepend = prependScrollAnchorRef.current;
    // Loading state can re-render this effect before the prepended rows arrive.
    // Keep the captured anchor until the controller transcript grows.
    if (pendingPrepend) {
      if (
        messageCount <= pendingPrepend.messageCount
        || chatMessages[0]?.id === pendingPrepend.firstMessageId
      ) return;
      prependScrollAnchorRef.current = null;
      if (autoScrollRafRef.current !== null) {
        cancelAnimationFrame(autoScrollRafRef.current);
        autoScrollRafRef.current = null;
      }
      const addedTurnCount = Math.max(0, count - prevCountRef.current);
      prevCountRef.current = count;
      scrollStateRef.current = {
        mode: "detached",
        lastItemCount: count,
        anchorId: pendingPrepend.anchorId,
      };
      followStreamRef.current = false;
      setDetachedFromBottom(true);
      const restoreGeneration = ++prependRestoreGenerationRef.current;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const target = scrollContainerRef.current;
          if (!target) return;
          // Preserve the viewport immediately from the list's total-height
          // delta. The keyed-row correction below then absorbs any remaining
          // difference as newly mounted turns are measured.
          const preservePrependOffset = (element: HTMLElement) => {
            element.scrollTop = pendingPrepend.scrollTop
              + Math.max(0, element.scrollHeight - pendingPrepend.scrollHeight);
          };
          preservePrependOffset(target);
          const currentAnchorIndex = pendingPrepend.anchorId
            ? timelineTurns.findIndex((item) => item.id === pendingPrepend.anchorId)
            : -1;
          const anchorIndex = currentAnchorIndex >= 0
            ? currentAnchorIndex
            : pendingPrepend.anchorIndex != null
            ? pendingPrepend.anchorIndex + addedTurnCount
            : -1;
          if (anchorIndex >= 0) {
            virtualizer.scrollToIndex(anchorIndex, { align: "start", behavior: "instant" });
          }
          let remainingFrames = 240;
          let stableFrames = 0;
          const restoreAnchor = () => requestAnimationFrame(() => {
            if (restoreGeneration !== prependRestoreGenerationRef.current) return;
            const currentTarget = scrollContainerRef.current;
            const anchorId = pendingPrepend.anchorId;
            if (!currentTarget || !anchorId || pendingPrepend.anchorTop == null) return;
            remainingFrames -= 1;
            const anchor = currentTarget.querySelector<HTMLElement>(
              `[data-row-id="${CSS.escape(anchorId)}"]`,
            );
            if (!anchor) {
              if (anchorIndex >= 0) {
                virtualizer.scrollToIndex(anchorIndex, { align: "start", behavior: "instant" });
              }
              // The first restoration frame can run before React commits the
              // larger list height, which clamps the initial offset. Retry the
              // deterministic height-delta restoration after scrollToIndex so
              // the stable keyed anchor is materialised on the next frame.
              preservePrependOffset(currentTarget);
              if (remainingFrames > 0) restoreAnchor();
              return;
            }
            const anchorRect = anchor.getBoundingClientRect();
            const scrollRect = currentTarget.getBoundingClientRect();
            if (anchorRect.bottom <= scrollRect.top || anchorRect.top >= scrollRect.bottom) {
              if (anchorIndex >= 0) {
                virtualizer.scrollToIndex(anchorIndex, { align: "start", behavior: "instant" });
              }
              preservePrependOffset(currentTarget);
              stableFrames = 0;
              if (remainingFrames > 0) restoreAnchor();
              return;
            }
            const correction = anchorRect.top - pendingPrepend.anchorTop;
            // A mounted virtual row can still carry a stale transform while
            // the virtualizer settles. Never apply a viewport-sized jump from
            // that transient position; rematerialize instead.
            if (Math.abs(correction) > currentTarget.clientHeight) {
              if (anchorIndex >= 0) {
                virtualizer.scrollToIndex(anchorIndex, { align: "start", behavior: "instant" });
              }
              stableFrames = 0;
              if (remainingFrames > 0) restoreAnchor();
              return;
            }
            if (Math.abs(correction) <= 0.5) stableFrames += 1;
            else {
              currentTarget.scrollTop += correction;
              stableFrames = 0;
            }
            if (remainingFrames > 0 && stableFrames < 60) restoreAnchor();
          });
          restoreAnchor();
        });
      });
      return;
    }
    if (countChanged) {
      scrollStateRef.current = reduceChatScrollState(scrollStateRef.current, {
        type: "items-changed",
        itemCount: count,
      });
      prevCountRef.current = count;
    }
    scrollStateRef.current = reduceChatScrollState(scrollStateRef.current, {
      type: "stream-tick",
      metrics: {
        scrollHeight: el.scrollHeight,
        scrollTop: el.scrollTop,
        clientHeight: el.clientHeight,
      },
    });
    const shouldFollow = shouldAutoScrollChat(scrollStateRef.current, {
      countChanged,
      streaming,
      metrics: {
        scrollHeight: el.scrollHeight,
        scrollTop: el.scrollTop,
        clientHeight: el.clientHeight,
      },
    });
    setDetachedFromBottom(
      scrollStateRef.current.mode === "detached" ||
      scrollStateRef.current.mode === "pending-new-message",
    );
    if (shouldFollow) {
      if (count > 0) {
        if (autoScrollRafRef.current !== null) cancelAnimationFrame(autoScrollRafRef.current);
        autoScrollRafRef.current = requestAnimationFrame(() => {
          autoScrollRafRef.current = null;
          if (countChanged) {
            if (scrollStateRef.current.mode === "jumping-to-bottom") {
              // Session open / explicit jump: keep clamping until row
              // measurements settle instead of a single estimated jump.
              runBottomClamp();
              return;
            }
            virtualizer.scrollToIndex(count - 1, { align: "end", behavior: streaming || safeMode ? "instant" : "smooth" });
            lastAutoScrollAtRef.current = Date.now();
            scrollStateRef.current = reduceChatScrollState(scrollStateRef.current, {
              type: "jump-complete",
              itemCount: count,
            });
            setDetachedFromBottom(false);
            return;
          }
          if (Date.now() - lastAutoScrollAtRef.current >= 250) {
            el.scrollTop = el.scrollHeight;
            lastAutoScrollAtRef.current = Date.now();
            scrollStateRef.current = reduceChatScrollState(scrollStateRef.current, {
              type: "jump-complete",
              itemCount: count,
            });
            setDetachedFromBottom(false);
          }
        });
      }
    }
    return () => {
      if (autoScrollRafRef.current !== null) {
        cancelAnimationFrame(autoScrollRafRef.current);
        autoScrollRafRef.current = null;
      }
    };
  }, [activeSessionId, chatMessages, prependScrollAnchorRef, runBottomClamp, safeMode, streaming, streamingAssistantVisibleChars, timelineTurns, virtualizer]);

  const virtualItems = virtualizer.getVirtualItems();
  const visibleStartIndex = virtualItems[0]?.index ?? 0;
  const visibleEndIndex = virtualItems[virtualItems.length - 1]?.index ?? visibleStartIndex;
  const turnLandmarks = useMemo(() => buildTurnLandmarks(timelineTurns), [timelineTurns]);

  const jumpToIndex = useCallback((index: number, align: "start" | "center" | "end" = "center") => {
    if (timelineTurns.length === 0) return;
    prependRestoreGenerationRef.current += 1;
    const nextIndex = Math.max(0, Math.min(index, timelineTurns.length - 1));
    if (align !== "end") {
      scrollStateRef.current = { ...scrollStateRef.current, anchorId: null };
    }
    scrollStateRef.current = align === "end"
      ? reduceChatScrollState(scrollStateRef.current, { type: "jump-to-bottom", itemCount: timelineTurns.length })
      : scrollStateRef.current;
    virtualizer.scrollToIndex(nextIndex, { align, behavior: "instant" });
    if (align === "end") {
      // Clamp until row measurements settle so the jump never lands short.
      runBottomClamp();
    }
  }, [runBottomClamp, timelineTurns.length, virtualizer]);

  const jumpToLatest = useCallback(() => {
    jumpToIndex(timelineTurns.length - 1, "end");
  }, [jumpToIndex, timelineTurns.length]);

  const diagnosticsTurn = (
    conversationDiagnostics?.turn && typeof conversationDiagnostics.turn === "object"
      ? conversationDiagnostics.turn as Record<string, unknown>
      : {}
  );
  const diagnosticsTiming = (
    conversationDiagnostics?.timing_breakdown && typeof conversationDiagnostics.timing_breakdown === "object"
      ? conversationDiagnostics.timing_breakdown as Record<string, unknown>
      : {}
  );
  const diagnosticsMessageCount = typeof conversationDiagnostics?.message_count === "number"
    ? conversationDiagnostics.message_count
    : null;
  const stressReasoningVisibleChars = chatMessages.reduce(
    (total, msg) => total + (msg.role === "reasoning" ? msg.text.length : 0),
    0,
  );

  return (
    <div
      data-testid="chat-panel"
      data-session-id={activeSessionId ?? ""}
      data-turn-state={turnState}
      data-streaming={streaming ? "true" : "false"}
      data-stream-visible-chars={streamingAssistantVisibleChars}
      data-reasoning-visible-chars={stressReasoningVisibleChars}
      data-recovery-polls={recoveryPollCount}
      className={cn("flex min-h-0 w-full flex-1 flex-col bg-background/45 relative", className)}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {isDragOver && (
        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-background/80 backdrop-blur-sm border-2 border-dashed border-primary rounded-lg pointer-events-none">
          <svg className="h-12 w-12 text-primary mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
          <p className="text-sm font-medium text-primary">Drop files to attach</p>
        </div>
      )}
      <div className="flex items-center justify-between border-b border-border bg-card/24 px-3 py-2 shrink-0 gap-2 backdrop-blur-xl">
        {onBack && (
          <Button variant="ghost" size="icon" className="h-8 w-8 md:hidden" onClick={onBack}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
        )}
        <div className="flex flex-col gap-1 min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusPill
              streaming={streaming}
              label={statusLabel}
              turnActive={confirmedTurnStatus?.turn_active}
              backendState={confirmedTurnStatus?.state}
              backendPhase={confirmedTurnStatus?.phase}
              backendStatus={confirmedTurnStatus?.status}
            />
            {safeMode && (
              <button
                type="button"
                onClick={disableSafeMode}
                className="inline-flex items-center gap-1 rounded-md bg-success/10 px-1.5 py-0.5 text-[10px] text-success/80 transition hover:bg-success/15 hover:text-success"
                title={safeModeNotice ?? "Safe render mode is active. Click to disable for this thread."}
              >
                <ShieldCheck className="h-2.5 w-2.5" />
                Safe render
              </button>
            )}
            {forkInfo?.parentSessionId && (
              <span className="inline-flex items-center gap-1 rounded-md bg-foreground/5 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                <CornerUpLeft className="h-2.5 w-2.5" />
                Forked from {forkInfo.parentTitle ?? forkInfo.parentSessionId}
              </span>
            )}
            {forkInfo && forkInfo.forkCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-md bg-foreground/5 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                <GitFork className="h-2.5 w-2.5" />
                {forkInfo.forkCount} {forkInfo.forkCount === 1 ? "branch" : "branches"}
              </span>
            )}
            {activeSessionId && (
              <Button
                variant="outline"
                size="sm"
                className="h-6 text-[10px] gap-1"
                disabled={streaming}
                onClick={() => void forkSession()}
                title="Fork session"
              >
                <GitFork className="h-3 w-3" />
                Fork
              </Button>
            )}
            {activeSessionId && (
              <Button
                variant="outline"
                size="sm"
                className="h-6 text-[10px] gap-1"
                onClick={() => setDiagnosticsOpen((open) => !open)}
                title="Chat diagnostics and recovery actions"
              >
                <Activity className="h-3 w-3" />
                Diagnostics
              </Button>
            )}
          </div>
          {activeSessionId && (
            <span className="font-mono text-[10px] text-muted-foreground truncate max-w-[300px]">
              {activeSessionId}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button
            variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground"
            onClick={() => { setSearchOpen((o) => !o); setTimeout(() => searchInputRef.current?.focus(), 10); }}
            title="Search messages (⌘F)"
          >
            <Search className="h-3.5 w-3.5" />
          </Button>
          {onClose && (
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
            )}
          </div>
          {turnState === "stalled" && (
            <div className="text-[11px] leading-4 text-amber-300/80">
              No backend activity recently. Spark will keep checking; you can wait, refresh, or redirect the turn.
            </div>
          )}
        </div>

      {shouldShowRecoveryPanel && (
        <div className="border-b border-border bg-card/18 px-3 py-2 text-[11px] text-muted-foreground">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <Activity className="h-3.5 w-3.5 text-foreground/60" />
              <span className="font-medium text-foreground/80">Chat diagnostics</span>
              <span className="truncate">
                {String(diagnosticsTurn.state ?? turnState)}
                {diagnosticsTurn.phase ? ` / ${String(diagnosticsTurn.phase)}` : ""}
              </span>
              {diagnosticsMessageCount !== null && (
                <span className="rounded bg-foreground/5 px-1.5 py-0.5">
                  {diagnosticsMessageCount} msgs
                </span>
              )}
              <span className="rounded bg-foreground/5 px-1.5 py-0.5">
                SSE {sseReconnectCount}
              </span>
              <span className="rounded bg-foreground/5 px-1.5 py-0.5">
                polls {recoveryPollCount}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-[10px]"
                onClick={() => void refreshConversationDiagnostics()}
                title="Refresh diagnostics"
              >
                <RefreshCw className="mr-1 h-3 w-3" />
                Refresh
              </Button>
              {recoveryActions.map((action) => (
                <Button
                  key={action.id}
                  variant={action.id === "stop" ? "destructive" : "outline"}
                  size="sm"
                  className="h-6 px-2 text-[10px]"
                  disabled={!action.enabled}
                  onClick={() => void runRecoveryAction(action.id)}
                  title={action.label}
                >
                  {recoveryActionBusy === action.id ? (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ) : action.id === "retry" ? (
                    <RotateCcw className="mr-1 h-3 w-3" />
                  ) : action.id === "continue" ? (
                    <PlayCircle className="mr-1 h-3 w-3" />
                  ) : action.id === "copy" ? (
                    <Copy className="mr-1 h-3 w-3" />
                  ) : action.id === "reload" ? (
                    <RefreshCw className="mr-1 h-3 w-3" />
                  ) : null}
                  {action.label}
                </Button>
              ))}
            </div>
          </div>
          {Object.keys(diagnosticsTiming).length > 0 && (
            <div className="mt-2 grid gap-1 sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries(diagnosticsTiming).slice(0, 8).map(([key, value]) => (
                <div key={key} className="rounded border border-border/60 bg-background/25 px-2 py-1">
                  <div className="truncate text-[10px] uppercase tracking-wide text-muted-foreground/70">
                    {key.replace(/_/g, " ")}
                  </div>
                  <div className="font-mono text-foreground/80">
                    {typeof value === "number" ? value.toFixed(3) : String(value)}
                  </div>
                </div>
              ))}
            </div>
          )}
          {diagnosticsError && (
            <div className="mt-1 text-destructive">{diagnosticsError}</div>
          )}
        </div>
      )}

      {/* Message search bar */}
      {searchOpen && (
        <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 bg-card/20 shrink-0">
          <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
          <input
            ref={searchInputRef}
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            placeholder="Search messages…"
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setSearchMatchIdx(0); }}
            onKeyDown={(e) => {
              if (e.key === "Enter") setSearchMatchIdx((i) => (i + 1) % Math.max(searchMatches.length, 1));
              if (e.key === "Escape") setSearchOpen(false);
            }}
          />
          {searchQuery && (
            <span className="text-[11px] text-muted-foreground shrink-0">
              {searchMatches.length ? `${(searchMatchIdx % searchMatches.length) + 1} / ${searchMatches.length}` : "0 results"}
            </span>
          )}
          <Button variant="ghost" size="icon" className="h-6 w-6" disabled={!searchMatches.length}
            onClick={() => setSearchMatchIdx((i) => (i - 1 + searchMatches.length) % searchMatches.length)}>
            <ChevronUp className="h-3 w-3" />
          </Button>
          <Button variant="ghost" size="icon" className="h-6 w-6" disabled={!searchMatches.length}
            onClick={() => setSearchMatchIdx((i) => (i + 1) % searchMatches.length)}>
            <ChevronDown className="h-3 w-3" />
          </Button>
          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => setSearchOpen(false)}>
            <X className="h-3 w-3" />
          </Button>
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <div
          data-testid="chat-scroll"
          className="h-full overflow-y-auto px-4 py-5 pr-8"
          style={{ overflowAnchor: "none" }}
          ref={scrollContainerRef}
        >
          {loadingHistory ? (
            <div className="flex flex-col gap-4 py-2">
            <MessageRowSkeleton />
            <MessageRowSkeleton />
            </div>
          ) : chatMessages.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <SparkAgentIcon className="mb-3 h-10 w-10 opacity-30" />
            <p className="text-sm">Start a conversation</p>
            <p className="text-xs mt-1 opacity-60">Type a message below</p>
            </div>
          ) : (
            <>
            {hasEarlier && (
              <div className="flex justify-center pt-1 pb-2">
                <button
                  type="button"
                  disabled={loadingEarlier}
                  onClick={() => void loadEarlierMessages()}
                  className="rounded-md bg-foreground/5 px-3 py-1 text-[11px] text-muted-foreground/60 transition hover:bg-foreground/8 hover:text-muted-foreground disabled:opacity-40"
                >
                  {loadingEarlier ? "Loading…" : "Load earlier messages"}
                </button>
              </div>
            )}
            <div ref={messageListRef} style={{ height: `${virtualizer.getTotalSize()}px`, position: "relative" }}>
            {virtualizer.getVirtualItems().map((vItem) => {
              const turn = timelineTurns[vItem.index];
              if (!turn) return null;
              const latestOutcome = turnOutcomes.at(-1) ?? null;
              const turnOutcome = outcomeForTimelineTurn(
                turn,
                turnOutcomes,
                vItem.index === timelineTurns.length - 1,
              );

              return (
                <div
                  key={turn.id}
                  data-index={vItem.index}
                  data-row-id={turn.id}
                  ref={measureRowElement}
                  style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vItem.start}px)` }}
                >
                  <div className="mx-auto w-full max-w-3xl px-4 pr-8">
                  <TimelineTurnGroup
                    turn={turn}
                    hasSession={Boolean(activeSessionId)}
                    streaming={streaming}
                    safeMode={safeMode}
                    sessionId={activeSessionId}
                    defaultWrap={chatWordWrap}
                    approvalBusy={approvalBusy}
                    onApprovalChoice={(item, choice) => void submitApproval(
                      choice,
                      typeof item.approval.action_id === "string" ? item.approval.action_id : undefined,
                    )}
                    onEdit={handleEdit}
                    onRetry={handleRetry}
                    onFork={handleFork}
                    onCopyText={copyText}
                    onPromoteToBrief={activeSessionId ? (message) => handlePromoteToBrief(message.source as AssistantMsg) : undefined}
                    onCopyExact={(message) => copyAssistant(message.source as AssistantMsg)}
                    onAttachPath={attachPath}
                    onFetchFullResult={fetchFullToolResult}
                    onSubagentSelect={onSubagentSelect}
                    onFeedbackSubmit={async (item, data) => {
                      if (!activeSessionId) throw new Error("No active session");
                      await api.submitFeedback(activeSessionId, data);
                      setChatMessages((previous) => previous.map((message) => (
                        item.sourceMessageIds.includes(message.id)
                          ? { ...message, submitted: true }
                          : message
                      )));
                    }}
                  />
                  {turnOutcome && (
                    <div className="ml-8 mt-3 max-w-[85%] space-y-2">
                      <ChangedFilesCard
                        changedFiles={turnOutcome?.changed_files}
                        onOpenFile={workspaceSlug ? (path) => window.dispatchEvent(new CustomEvent("spark:right-panel-open", {
                          detail: { tab: "changes", path },
                        })) : undefined}
                      />
                      <PlanCard
                        plan={turnOutcome === latestOutcome ? conversationPlan ?? turnOutcome.plan : turnOutcome.plan}
                        onOpenPlan={() => window.dispatchEvent(new CustomEvent("spark:brief-open"))}
                      />
                    </div>
                  )}
                  </div>
                </div>
              );
            })}
            </div>
            </>
          )}
        </div>
        <TimelineMinimap
          landmarks={turnLandmarks}
          visibleStartTurnIndex={visibleStartIndex}
          visibleEndTurnIndex={visibleEndIndex}
          onJumpToTurn={jumpToIndex}
        />
        {detachedFromBottom && timelineTurns.length > 0 && (
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="absolute bottom-3 right-6 z-30 h-8 w-8 rounded-md bg-background/90 shadow-sm backdrop-blur"
            title="Jump to latest"
            onClick={jumpToLatest}
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="mx-4 mb-2 shrink-0 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2"
        >
          <p className="text-xs text-destructive">{error}</p>
        </div>
      )}

      {editingUser && (
        <div className="border-t border-border px-4 py-2 bg-card/24 shrink-0 space-y-2">
          <p className="text-xs text-muted-foreground">Edit and retry</p>
          <textarea
            className="w-full rounded-md border border-input bg-background/40 px-2 py-1.5 text-xs min-h-[72px] outline-none focus:ring-1 focus:ring-foreground/20"
            value={editingUser.text}
            onChange={(e) => setEditingUser({ ...editingUser, text: e.target.value })}
          />
          <div className="flex gap-2 justify-end">
            <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setEditingUser(null)}>
              Cancel
            </Button>
            <Button
              size="sm"
              className="h-7 text-xs"
              disabled={streaming}
              onClick={() => {
                const { sessionIdx, text } = editingUser;
                setEditingUser(null);
                void retryMessage(sessionIdx, text);
              }}
            >
              Retry with edited message
            </Button>
          </div>
        </div>
      )}

      <SessionInfoBar stats={sessionStats} />

      {activeSessionId && <BriefPanel sessionId={activeSessionId} />}

      <PendingActionTray
        actions={pendingActions}
        busyActionIds={busyActionIds}
        onApprovalChoice={(action, choice) => runPendingAction(
          action,
          () => api.submitConversationApproval(activeSessionId ?? action.session_id, choice, false, action.action_id),
        )}
        onSubmitInput={(action, response) => runPendingAction(
          action,
          () => api.submitConversationInput(activeSessionId ?? action.session_id, action.action_id, response),
        )}
      />

      <ContextTray
        items={contextItems}
        onRemove={removeContextItem}
        onUpdateMode={updateContextMode}
        onUpdateScope={updateContextScope}
        onUpdateItem={updateContextItem}
        onSummarize={(id) => void summarizeContextItem(id)}
      />

      <PromptBar
        input={input}
        setInput={setInput}
        streaming={streaming}
        onSend={() => void sendMessage()}
        onStop={() => void stop()}
        onUploadFiles={uploadFiles}
        onAttachPath={attachPath}
        onRemoveContextItem={removeContextItem}
        onUpdateContextMode={updateContextMode}
        disabled={!!editingUser}
        workspaceSlug={workspaceSlug}
        contextItems={contextItems}
        sessionId={activeSessionId}
      />
    </div>
  );
}
