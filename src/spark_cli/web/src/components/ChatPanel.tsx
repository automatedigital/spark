import { memo, useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ChevronLeft,
  X,
  User,
  Loader2,
  GitFork,
  RotateCcw,
  Copy,
  Pencil,
  Search,
  ChevronUp,
  ChevronDown,
  CornerUpLeft,
  FileText,
  ShieldCheck,
  Activity,
  RefreshCw,
  PlayCircle,
} from "lucide-react";
// Square/Send/handleKeyDown removed — now handled by PromptBar
import { api, openExternal } from "@/lib/api";
import type { SessionMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/Markdown";
import { BrandLogo } from "@/components/BrandLogo";
import { Button } from "@/components/ui/button";
import { useEventBus, BUS_GAP_TOPIC, BUS_RECONNECTED_TOPIC } from "@/hooks/useEventBus";
import {
  estimateAssistantRowSize,
  findLiveRowIndex,
  shouldSkipRowMeasurement,
} from "@/lib/rowMeasurement";
import { ToolCallBubble } from "@/components/chat/ToolCallBubble";
import { ReasoningBubble } from "@/components/chat/ReasoningBubble";
import { ApprovalPrompt } from "@/components/chat/ApprovalPrompt";
import { FeedbackForm } from "@/components/chat/FeedbackForm";
import { MODEL_LOADING_LABEL, StatusPill } from "@/components/chat/StatusPill";
import { PromptBar } from "@/components/chat/PromptBar";
import { ContextTray } from "@/components/chat/ContextTray";
import { BriefPanel } from "@/components/chat/BriefPanel";
import { SessionInfoBar } from "@/components/chat/SessionInfoBar";
import type { SessionStats } from "@/components/chat/SessionInfoBar";
import { TimelineMinimap, buildTimelineMinimapItems, type TimelineSourceItem } from "@/components/chat/TimelineMinimap";
import { MessageRowSkeleton } from "@/components/Skeleton";
import { setTrayStatus } from "@/lib/desktop";
import { tokenizeUserBubbleText } from "@/lib/userBubbleTokens";
import { makeFileContextItem, briefApi } from "@/lib/context";
import type { ContextItem, InclusionMode, ContextScope } from "@/lib/context";
import {
  backendTurnStatusLabel,
  nextChatTurnState,
  recoverTurnStateFromBackend,
  type ChatTurnState,
} from "@/lib/chatTurnState";
import {
  consumeRecoverySignal,
  decideRecoveryPoll,
  initialRecoverySignalBudget,
} from "@/lib/chatRecovery";
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
  applyStreamRenderSnapshotState,
  shouldEnableSafeMode,
  shouldApplyStreamRenderSnapshot,
  type LongTaskSample,
} from "@/lib/renderHealth";
import {
  initialChatScrollState,
  reduceChatScrollState,
  shouldAutoScrollChat,
} from "@/lib/chatScrollState";
import {
  localTurnCache,
  mergeSyncedMessages,
  rememberLocalTurn,
  type ChatMessage,
} from "@/lib/chatTranscriptMerge";
import { isTauri } from "@/sidecar";
import { liveStreamFlushInterval, snapshotLiveStream, windowLiveStream } from "@/lib/liveStreamWindow";
import { copyExactAssistantContent, exactAssistantContent } from "@/lib/exactMessage";
import {
  appendBoundedText,
  boundText,
  COMPLETED_TEXT_WINDOW_CHARS,
  REASONING_WINDOW_CHARS,
} from "@/lib/textWindow";

let _msgId = 0;
const nid = () => `m${++_msgId}`;
const hasText = (value: string | null | undefined) => Boolean(value && value.length > 0);
const CHAT_WORD_WRAP_CHANGED_EVENT = "spark:chat-word-wrap-changed";
const CHAT_RECOVERY_DEBUG_KEY = "spark:chat-recovery-debug";

function debugChatRecovery(event: string, payload: unknown) {
  try {
    const enabled = window.localStorage.getItem(CHAT_RECOVERY_DEBUG_KEY);
    if (enabled !== "1" && enabled !== "true") return;
    console.debug(`[spark-chat-recovery] ${event}`, payload);
  } catch {
    /* debug logging is best-effort */
  }
}

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
  className?: string;
}

function sessionMessagesToChat(messages: SessionMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  // Build a map of tool_call_id -> tool name from assistant tool_calls for fallback
  const toolCallNames: Record<string, string> = {};
  for (const m of messages) {
    if (m.role === "assistant" && m.tool_calls) {
      for (const tc of m.tool_calls) {
        if (tc.id && tc.function?.name) toolCallNames[tc.id] = tc.function.name;
      }
    }
  }
  messages.forEach((m, i) => {
    const baseId = m.id ? `db:${m.id}` : `db:${m.role}:${i}`;
    if (m.role === "user") {
      // Skip internal system-injected continuation messages (e.g. codex ack loop)
      if ((m.content ?? "").startsWith("[System:")) return;
      out.push({ id: baseId, role: "user", content: m.content ?? "", sessionIdx: m.message_index ?? i });
    } else if (m.role === "assistant") {
      const reasoning = m.reasoning?.trim();
      if (reasoning) {
        const bounded = boundText(reasoning, REASONING_WINDOW_CHARS);
        out.push({ id: `${baseId}:reasoning`, role: "reasoning", text: bounded.text,
          totalChars: bounded.totalChars, omittedChars: bounded.omittedChars });
      }
      if (hasText(m.content)) {
        const bounded = boundText(m.content ?? "", COMPLETED_TEXT_WINDOW_CHARS);
        out.push({ id: baseId, role: "assistant", content: bounded.text,
          liveTotalChars: bounded.totalChars, liveOmittedChars: bounded.omittedChars });
      }
    } else if (m.role === "tool") {
      const toolId = m.tool_call_id ?? "";
      const result = String(m.result_preview ?? m.content ?? "");
      out.push({
        id: toolId ? `tool:${toolId}` : baseId,
        role: "tool",
        toolId,
        name: m.tool_name ?? toolCallNames[toolId] ?? "tool",
        args: {},
        result,
        resultTruncated: Boolean(m.result_truncated ?? m.has_full_result) || undefined,
        done: true,
      });
    }
  });
  return out;
}

function latestAssistantContentLength(messages: ChatMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === "assistant" && msg.content) return msg.liveTotalChars ?? msg.content.length;
  }
  return 0;
}

// ── Memoized row components ───────────────────────────────────────────────────
// Defined at module scope so their identity is stable — React.memo bails out
// any row whose props haven't changed, preventing re-renders of the full
// message list on every streaming token.

function SparkAgentIcon({ className = "h-4 w-4" }: { className?: string }) {
  return <BrandLogo className={className} />;
}

function SparkAgentAvatar() {
  return (
    <div className="shrink-0 h-7 w-7 rounded-full flex items-center justify-center bg-success/20">
      <SparkAgentIcon />
    </div>
  );
}

function renderTokens(text: string): React.ReactNode[] {
  return tokenizeUserBubbleText(text).map((token, index) => {
    if (token.type === "highlight") {
      return <span key={index} className="text-primary font-medium">{token.text}</span>;
    }
    if (token.type === "link") {
      return (
        <a
          key={index}
          href={token.href}
          target="_blank"
          rel="noreferrer"
          onClick={(event) => openUserBubbleLink(event, token.href)}
          className="break-words text-primary/90 underline decoration-primary/25 underline-offset-2 transition-colors hover:text-primary hover:decoration-primary/60"
        >
          {token.text}
        </a>
      );
    }
    return token.text;
  });
}

function openUserBubbleLink(event: MouseEvent<HTMLAnchorElement>, href: string) {
  event.stopPropagation();
  if (!isTauri()) return;
  event.preventDefault();
  void openExternal(href);
}

type UserMsg = Extract<ChatMessage, { role: "user" }>;
type AssistantMsg = Extract<ChatMessage, { role: "assistant" }>;
type ToolMsg = Extract<ChatMessage, { role: "tool" }>;
type ReasoningMsg = Extract<ChatMessage, { role: "reasoning" }>;
type ApprovalMsg = Extract<ChatMessage, { role: "approval" }>;
type NoteMsg = Extract<ChatMessage, { role: "note" }>;
type FeedbackFormMsg = Extract<ChatMessage, { role: "feedback_form" }>;

function toolDurationSeconds(msg: ToolMsg): number | undefined {
  if (typeof msg.durationSeconds === "number") return Math.max(0, msg.durationSeconds);
  if (typeof msg.startedAt === "number" && typeof msg.endedAt === "number") {
    return Math.max(0, msg.endedAt - msg.startedAt);
  }
  return undefined;
}

const MODE_SHORT: Record<string, string> = {
  path_only: "path", excerpt: "excerpt", summary: "summary", full: "full", search: "search",
};

const UserRow = memo(function UserRow({
  msg, hasSession, streaming, onEdit, onRetry, onFork, onCopy,
}: {
  msg: UserMsg;
  hasSession: boolean;
  streaming: boolean;
  onEdit: (idx: number, text: string) => void;
  onRetry: (idx: number) => void;
  onFork: (idx: number) => void;
  onCopy: (text: string) => void;
}) {
  const [expandedChip, setExpandedChip] = useState<string | null>(null);

  return (
    <div className="flex gap-2 flex-row-reverse group/msg">
      <div className="shrink-0 h-6 w-6 rounded-md flex items-center justify-center text-xs bg-foreground/8 text-muted-foreground">
        <User className="h-3.5 w-3.5" />
      </div>
      <div className="max-w-[85%] flex flex-col items-end gap-1">
        {msg.redirect && (
          <span className="text-[10px] text-muted-foreground/60">↩ redirect</span>
        )}
        <div className="rounded-lg px-3 py-2 text-sm bg-foreground/8 text-foreground relative">
          <p className="whitespace-pre-wrap leading-relaxed">{renderTokens(msg.content)}</p>
          {hasSession && msg.sessionIdx != null && (
            <div className="absolute -top-2 right-0 opacity-0 group-hover/msg:opacity-100 flex gap-1 transition-opacity">
              <Button type="button" variant="ghost" size="icon" className="h-6 w-6" title="Edit & retry"
                onClick={() => onEdit(msg.sessionIdx!, msg.content)}>
                <Pencil className="h-3 w-3" />
              </Button>
              <Button type="button" variant="ghost" size="icon" className="h-6 w-6" title="Retry"
                disabled={streaming} onClick={() => onRetry(msg.sessionIdx!)}>
                <RotateCcw className="h-3 w-3" />
              </Button>
              <Button type="button" variant="ghost" size="icon" className="h-6 w-6" title="Fork from here"
                disabled={streaming} onClick={() => onFork(msg.sessionIdx!)}>
                <GitFork className="h-3 w-3" />
              </Button>
              <Button type="button" variant="ghost" size="icon" className="h-6 w-6" title="Copy"
                onClick={() => onCopy(msg.content)}>
                <Copy className="h-3 w-3" />
              </Button>
            </div>
          )}
        </div>
        {msg.contextItems && msg.contextItems.length > 0 && (
          <div className="flex flex-wrap gap-1 justify-end">
            {msg.contextItems.map((item) => {
              const name = item.label ?? item.source_path?.split("/").pop() ?? item.id;
              const modeLabel = MODE_SHORT[item.inclusion_mode] ?? item.inclusion_mode;
              const isExpanded = expandedChip === item.id;
              return (
                <div key={item.id} className="relative">
                  <button
                    type="button"
                    onClick={() => setExpandedChip(isExpanded ? null : item.id)}
                    className="flex items-center gap-1 rounded-md bg-foreground/6 px-1.5 py-0.5 text-[10px] text-muted-foreground hover:bg-foreground/9 hover:text-foreground transition"
                    title={`${name} · ${modeLabel} mode`}
                  >
                    <span className="font-mono truncate max-w-[80px]">{name}</span>
                    <span className="opacity-50">·</span>
                    <span>{modeLabel}</span>
                  </button>
                  {isExpanded && item.content && (
                    <div className="absolute bottom-full mb-1 right-0 z-50 w-72 rounded-md border border-border bg-popover/95 shadow-lg p-2 text-[11px] font-mono text-foreground/80 max-h-40 overflow-y-auto whitespace-pre-wrap backdrop-blur-xl">
                      {item.content}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
});

const AssistantRow = memo(function AssistantRow({
  msg,
  safeMode,
  defaultWrap,
  onPromoteToBrief,
  onCopyExact,
}: {
  msg: AssistantMsg;
  safeMode?: boolean;
  defaultWrap?: boolean;
  onPromoteToBrief?: (msg: AssistantMsg) => void;
  onCopyExact?: (msg: AssistantMsg) => void;
}) {
  return (
    <div className="flex gap-2 group/amsg">
      <SparkAgentAvatar />
      <div className="w-full max-w-[85%] rounded-lg px-3 py-2 text-sm bg-transparent text-foreground min-w-0 relative">
        {msg.content ? (
          <>
            {Boolean(msg.liveOmittedChars) && (
              <div className="mb-2 text-[11px] text-muted-foreground/60">
                Showing the latest {msg.content.length.toLocaleString()} of {msg.liveTotalChars?.toLocaleString()} characters
                {!msg.streaming && "; the complete response remains saved in this session"}
              </div>
            )}
            <Markdown
              content={msg.content}
              streaming={msg.streaming}
              showStreamingCursor={msg.streaming}
              safeMode={safeMode}
              renderRevision={msg.renderRevision}
              defaultWrap={defaultWrap}
            />
          </>
        ) : (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Loader2 className={`h-3 w-3 ${safeMode ? "" : "animate-spin"}`} />
            <span className="text-xs">Thinking…</span>
          </span>
        )}
        {!msg.streaming && msg.content && (onPromoteToBrief || onCopyExact) && (
          <div className="absolute -top-2 right-0 opacity-0 group-hover/amsg:opacity-100 transition-opacity flex gap-1">
            {onCopyExact && (
              <Button type="button" variant="ghost" size="icon" className="h-6 w-6"
                title="Copy complete response" onClick={() => onCopyExact(msg)}>
                <Copy className="h-3 w-3" />
              </Button>
            )}
            {onPromoteToBrief && (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              title="Promote to brief"
              onClick={() => onPromoteToBrief(msg)}
            >
              <FileText className="h-3 w-3" />
            </Button>
            )}
          </div>
        )}
        {!msg.streaming && msg.usage && msg.usage.totalTokens > 0 && (
          <div className="mt-1 text-[10px] text-muted-foreground/40 tabular-nums">
            {msg.usage.totalTokens >= 1000
              ? `${(msg.usage.totalTokens / 1000).toFixed(1)}K tokens`
              : `${msg.usage.totalTokens} tokens`}
            {msg.usage.costUsd != null && msg.usage.costUsd > 0 && (
              <> · ${msg.usage.costUsd < 0.01 ? msg.usage.costUsd.toFixed(4) : msg.usage.costUsd.toFixed(2)}</>
            )}
          </div>
        )}
      </div>
    </div>
  );
});

const ToolRow = memo(function ToolRow({
  msg,
  repeatCount,
  safeMode,
  onAttachPath,
  onFetchFullResult,
}: {
  msg: ToolMsg;
  repeatCount: number;
  safeMode?: boolean;
  onAttachPath?: (path: string) => void;
  onFetchFullResult?: (toolId: string) => Promise<string | null>;
}) {
  return (
    <div className="pl-9">
      <ToolCallBubble
        name={msg.name} args={msg.args} result={msg.result} done={msg.done}
        startedAt={msg.startedAt} endedAt={msg.endedAt} durationSeconds={msg.durationSeconds}
        repeatCount={repeatCount > 0 ? repeatCount : undefined}
        resultTruncated={msg.resultTruncated}
        safeMode={safeMode}
        onAttachPath={onAttachPath}
        onFetchFullResult={onFetchFullResult ? () => onFetchFullResult(msg.toolId) : undefined}
      />
    </div>
  );
});

const ReasoningRow = memo(function ReasoningRow({ msg, isActive, safeMode }: { msg: ReasoningMsg; isActive?: boolean; safeMode?: boolean }) {
  return <div className="pl-9">
    {Boolean(msg.omittedChars) && (
      <p className="mb-1 text-[10px] text-muted-foreground">Earlier reasoning hidden to keep this chat responsive.</p>
    )}
    <ReasoningBubble text={msg.text} isActive={isActive} safeMode={safeMode} />
  </div>;
});

const ApprovalRow = memo(function ApprovalRow({
  msg, disabled, onChoice,
}: {
  msg: ApprovalMsg;
  disabled: boolean;
  onChoice: (c: "once" | "session" | "always" | "deny") => void;
}) {
  return (
    <div className="pl-2">
      <ApprovalPrompt
        command={String(msg.approval.command ?? "")}
        description={String(msg.approval.description ?? "")}
        disabled={disabled || !!msg.resolved}
        onChoice={onChoice}
      />
    </div>
  );
});

const NoteRow = memo(function NoteRow({ msg }: { msg: NoteMsg }) {
  return <p className="text-xs text-muted-foreground italic pl-2">{msg.text}</p>;
});

const FeedbackRow = memo(function FeedbackRow({
  msg, sessionId, onSubmitted,
}: {
  msg: FeedbackFormMsg;
  sessionId: string | null;
  onSubmitted: (id: string) => void;
}) {
  const handleSubmit = async (data: { name: string; email: string; area: string; note: string }) => {
    if (!sessionId) throw new Error("No active session");
    await api.submitFeedback(sessionId, data);
    onSubmitted(msg.id);
  };
  return (
    <div className="pl-2">
      <FeedbackForm onSubmit={handleSubmit} submitted={!!msg.submitted} />
    </div>
  );
});

// ── ChatPanel ─────────────────────────────────────────────────────────────────

export function ChatPanel({
  sessionId,
  onClose,
  onBack,
  onSessionCreated,
  onSessionUpdated,
  initialMessage,
  workspaceSlug,
  className,
}: ChatPanelProps) {
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
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
  const [activeSessionId, setActiveSessionId] = useState<string | null>(sessionId);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [hasEarlier, setHasEarlier] = useState(false);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const HISTORY_PAGE = 50;
  const [statusLabel, setStatusLabel] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [editingUser, setEditingUser] = useState<{ sessionIdx: number; text: string } | null>(null);
  const [sessionStats, setSessionStats] = useState<SessionStats>({});
  const [forkInfo, setForkInfo] = useState<{
    parentSessionId: string | null;
    parentTitle: string | null;
    forkCount: number;
  } | null>(null);
  const [safeMode, setSafeMode] = useState(() => readSafeMode(sessionId));
  const [safeModeNotice, setSafeModeNotice] = useState<string | null>(null);
  const [chatWordWrap, setChatWordWrap] = useState(false);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [conversationDiagnostics, setConversationDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [recoveryActionBusy, setRecoveryActionBusy] = useState<RecoveryActionId | null>(null);
  const [sseReconnectCount, setSseReconnectCount] = useState(0);
  const [recoveryPollCount, setRecoveryPollCount] = useState(0);

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const activeSessionRef = useRef<string | null>(sessionId);
  const streamingRef = useRef(false);
  const turnStateRef = useRef<ChatTurnState>("idle");
  const safeModeRef = useRef(safeMode);
  const activeTurnSessionIdRef = useRef<string | null>(null);
  const activeSessionAliasesRef = useRef<Set<string>>(new Set(sessionId ? [sessionId] : []));
  const sessionRecoverySeqRef = useRef(0);
  // Token batching: accumulate tokens and flush once per animation frame
  const tokenBufferRef = useRef<string[]>([]);
  const rafPendingRef = useRef<number | null>(null);
  const flushTimerRef = useRef<number | null>(null);
  // Reasoning batching: same rAF coalescing as tokens, so a model that streams
  // reasoning in many small deltas triggers at most one re-render per frame
  // instead of one per delta.
  const reasoningBufferRef = useRef("");
  const reasoningBufferedCharsRef = useRef(0);
  const reasoningRafRef = useRef<number | null>(null);
  // Timestamp of the last chat event received for the active turn. Drives the
  // stall watchdog that recovers from a silently-dropped turn (lost SSE).
  const lastEventAtRef = useRef<number>(0);
  // Timestamp of the last visible assistant token. Status/reasoning events can
  // keep the backend heartbeat alive while the rendered answer itself is stuck.
  const lastTokenAtRef = useRef<number>(0);
  const lastIdleRecoveryPollAtRef = useRef<number>(0);
  // Guards against overlapping turn-status re-sync polls.
  const resyncInFlightRef = useRef(false);
  const recoverySignalBudgetRef = useRef(initialRecoverySignalBudget());
  // Exact oversized messages live outside React render state. They are loaded
  // only for explicit copy/search/artifact actions and never mounted in the DOM.
  const exactAssistantContentRef = useRef<Map<string, string>>(new Map());
  const exactSearchRequestKeyRef = useRef("");
  const resyncTurnStateRef = useRef<((options?: { allowIdle?: boolean }) => Promise<void>) | null>(null);
  // SSE is the fast path; the backend stream snapshot is the source of truth.
  // Track revisions so recovery polling only repaints when the server advanced.
  const streamRevisionRef = useRef(0);
  const streamTextCharsRef = useRef(0);
  // Keep the viewport pinned to the live tail while the user is following the
  // stream, but stop auto-scrolling as soon as they deliberately scroll upward.
  const followStreamRef = useRef(true);
  const scrollStateRef = useRef(initialChatScrollState());
  const prependScrollAnchorRef = useRef<{
    scrollHeight: number;
    scrollTop: number;
    anchorId: string | null;
  } | null>(null);
  const [detachedFromBottom, setDetachedFromBottom] = useState(false);

  activeSessionRef.current = activeSessionId;
  if (activeSessionId) activeSessionAliasesRef.current.add(activeSessionId);
  streamingRef.current = streaming;
  turnStateRef.current = turnState;
  safeModeRef.current = safeMode;

  useEffect(() => () => {
    if (flushTimerRef.current !== null) clearTimeout(flushTimerRef.current);
    if (rafPendingRef.current !== null) cancelAnimationFrame(rafPendingRef.current);
    if (reasoningRafRef.current !== null) cancelAnimationFrame(reasoningRafRef.current);
    flushTimerRef.current = null;
    rafPendingRef.current = null;
    reasoningRafRef.current = null;
    tokenBufferRef.current = [];
    reasoningBufferRef.current = "";
    reasoningBufferedCharsRef.current = 0;
  }, []);

  const rememberActiveSessionAliases = useCallback((...ids: Array<string | null | undefined>) => {
    ids.forEach((id) => {
      if (id) activeSessionAliasesRef.current.add(id);
    });
  }, []);

  const appendRecoveredStaleTurnNote = useCallback((text: string) => {
    setChatMessages((prev) => {
      if (prev.some((m) => m.role === "note" && m.text === text)) return prev;
      return [...prev, { id: nid(), role: "note", text }];
    });
  }, []);

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

  const resetActiveSessionAliases = useCallback((...ids: Array<string | null | undefined>) => {
    activeSessionAliasesRef.current = new Set(ids.filter((id): id is string => Boolean(id)));
  }, []);

  const isCurrentSessionResponse = useCallback((
    recoverySeq: number,
    ...ids: Array<string | null | undefined>
  ) => {
    if (recoverySeq !== sessionRecoverySeqRef.current) return false;
    const current = activeSessionRef.current;
    return Boolean(current && (
      ids.includes(current) ||
      ids.some((id) => typeof id === "string" && activeSessionAliasesRef.current.has(id))
    ));
  }, []);

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
  }, []);

  // Desktop (§3.1): reflect agent activity in the menu-bar tray indicator.
  useEffect(() => {
    void setTrayStatus(streaming, streaming ? "Spark — working…" : undefined);
  }, [streaming]);

  useEffect(() => {
    if (sessionId && sessionId === activeSessionRef.current && streamingRef.current) {
      return;
    }
    // Cancel any pending token flushes from the previous session
    if (flushTimerRef.current !== null) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
      tokenBufferRef.current = [];
    }
    if (rafPendingRef.current !== null) {
      cancelAnimationFrame(rafPendingRef.current);
      rafPendingRef.current = null;
    }
    tokenBufferRef.current = [];
    if (reasoningRafRef.current !== null) {
      cancelAnimationFrame(reasoningRafRef.current);
      reasoningRafRef.current = null;
      reasoningBufferRef.current = "";
      reasoningBufferedCharsRef.current = 0;
    }
    prependScrollAnchorRef.current = null;
    setActiveSessionId(sessionId);
    activeSessionRef.current = sessionId;
    resetActiveSessionAliases(sessionId);
    const recoverySeq = ++sessionRecoverySeqRef.current;
    const optimistic: ChatMessage[] = initialMessage
      ? [{ id: nid(), role: "user", content: initialMessage }]
      : [];
    const cachedTranscript = sessionId ? localTurnCache.get(sessionId) ?? [] : [];
    const initialTranscript = cachedTranscript.length > 0 ? cachedTranscript : optimistic;
    setChatMessages(initialTranscript);
    setError(null);
    // Mounting with an initialMessage means the composer just started a turn for
    // this new thread (its postConversation already kicked off the agent). Show
    // the typing indicator right away instead of waiting for the first token —
    // which can be many seconds on a slow model. Cleared below if history shows
    // the turn already finished, and by the chat.turn_done event otherwise.
    setStreaming(!!initialMessage);
    setStatusLabel(initialMessage ? MODEL_LOADING_LABEL : null);
    lastTokenAtRef.current = initialMessage ? Date.now() : 0;
    streamRevisionRef.current = 0;
    streamTextCharsRef.current = latestAssistantContentLength(initialTranscript);
    recoverySignalBudgetRef.current = initialRecoverySignalBudget();
    exactAssistantContentRef.current.clear();
    exactSearchRequestKeyRef.current = "";
    prevCountRef.current = 0;
    lastAutoScrollAtRef.current = 0;
    scrollStateRef.current = reduceChatScrollState(initialChatScrollState(initialTranscript.length), {
      type: "jump-to-bottom",
      itemCount: initialTranscript.length,
    });
    setDetachedFromBottom(false);
    activeTurnSessionIdRef.current = null;
    followStreamRef.current = true;
    setEditingUser(null);
    setSessionStats({});
    setForkInfo(null);
    const restoredSafeMode = readSafeMode(sessionId);
    setSafeMode(restoredSafeMode);
    setSafeModeNotice(restoredSafeMode ? "Recovered this thread in safe mode." : null);
    if (sessionId) {
      const selectedSessionId = sessionId;
      void api.getTurnStatus(selectedSessionId).then(async (status) => {
        debugChatRecovery("initial-turn-status", status.diagnostics ?? status);
        const recoveryStillCurrent = (...ids: Array<string | null | undefined>) => (
          isCurrentSessionResponse(recoverySeq, selectedSessionId, ...ids)
        );
        if (!recoveryStillCurrent(
          status.resolved_session_id,
          status.latest_session_id,
          status.active_turn_session_id,
        )) return;
        rememberActiveSessionAliases(
          selectedSessionId,
          status.resolved_session_id,
          status.latest_session_id,
          status.active_turn_session_id,
        );
        activeTurnSessionIdRef.current = status.turn_active
          ? status.active_turn_session_id ?? selectedSessionId
          : null;
        const recoveredState = recoverTurnStateFromBackend({
          turnActive: status.turn_active,
          phase: status.phase,
          state: status.state,
          interruptRequested: status.interrupt_requested,
        });
        setTurnState(recoveredState);
        setStatusLabel(backendTurnStatusLabel({
          turnActive: status.turn_active,
          phase: status.phase,
          state: status.state,
          status: status.status,
          idleForSeconds: status.idle_for_seconds,
        }));
        if (status.turn_active) {
          lastEventAtRef.current = Date.now();
          const snapshotSessionId = status.active_turn_session_id ?? selectedSessionId;
          try {
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
              syncLiveAssistantSnapshot(
                snapshot.stream_text,
                snapshot.stream_revision,
                snapshot.stream_text_start ?? 0,
              );
            }
            if (!snapshot.turn_active) {
              setTurnState("idle");
              setStatusLabel("Finalizing from saved history…");
              flushPendingStream();
              finalizeAssistant();
              try {
                const resp = await api.getSessionMessages(selectedSessionId, HISTORY_PAGE);
                if (!recoveryStillCurrent(resp.session_id)) return;
                rememberActiveSessionAliases(selectedSessionId, resp.session_id);
                const mapped = sessionMessagesToChat(
                  resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
                );
                setChatMessages((prev) => mergeSyncedMessages(
                  mapped,
                  prev,
                  resp.session_id ?? selectedSessionId,
                  { preferSyncedAssistants: true, syncedComplete: !(resp.has_earlier ?? false) },
                ));
              } catch {
                /* final history recovery is best-effort */
              } finally {
                setStatusLabel(null);
              }
            }
          } catch {
            /* snapshot hydration is best-effort */
          }
          return;
        }
        flushPendingStream();
        finalizeAssistant();
        try {
          const resp = await api.getSessionMessages(selectedSessionId, HISTORY_PAGE);
          if (!recoveryStillCurrent(resp.session_id)) return;
          const mapped = sessionMessagesToChat(
            resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
          );
          const hasAssistant = mapped.some((m) => m.role === "assistant" && m.content.trim());
          setChatMessages((prev) => mergeSyncedMessages(
            mapped,
            initialTranscript.length > 0 ? prev : optimistic,
            resp.session_id ?? selectedSessionId,
            { preferSyncedAssistants: true, syncedComplete: !(resp.has_earlier ?? false) },
          ));
          setHasEarlier(resp.has_earlier ?? false);
          if ((initialMessage || initialTranscript.some((m) => m.role === "assistant" && m.streaming)) && !hasAssistant) {
            appendRecoveredStaleTurnNote("This turn was no longer active after reconnecting. You can retry or send a follow-up.");
          }
        } catch {
          /* history recovery is best-effort */
        }
      }).catch(() => {
        /* selected-session turn recovery is best-effort */
      });
      api.getSessionForks(sessionId).then((info) => {
        if (!isCurrentSessionResponse(recoverySeq, sessionId)) return;
        setForkInfo({
          parentSessionId: info.parent_session_id,
          parentTitle: info.parent_title,
          forkCount: info.fork_count,
        });
      }).catch(() => {});
      setLoadingHistory(true);
      setHasEarlier(false);
      api
        .getSessionMessages(sessionId, HISTORY_PAGE)
        .then((resp) => {
          if (!isCurrentSessionResponse(recoverySeq, sessionId, resp.session_id)) return;
          // If the requested session was compressed, the backend returns
          // the leaf session_id. Re-pin our refs so streaming events and
          // turn_done re-fetches use the agent's actual current session.
          rememberActiveSessionAliases(sessionId, resp.session_id);
          if (resp.session_id && resp.session_id !== activeSessionRef.current) {
            activeSessionRef.current = resp.session_id;
            setActiveSessionId(resp.session_id);
          }
          const mapped = sessionMessagesToChat(
            resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
          );
          setChatMessages((prev) => {
            const merged = mergeSyncedMessages(
              mapped,
              initialTranscript.length > 0 ? prev : optimistic,
              resp.session_id ?? sessionId,
              {
                preserveLocalAssistantPrefix: Boolean(activeTurnSessionIdRef.current),
                syncedComplete: !(resp.has_earlier ?? false),
              },
            );
            if (activeTurnSessionIdRef.current) {
              streamTextCharsRef.current = Math.max(
                streamTextCharsRef.current,
                latestAssistantContentLength(merged),
              );
            }
            return merged;
          });
          setHasEarlier(resp.has_earlier ?? false);
          // If history already contains an assistant reply, the turn finished
          // before/at mount — clear the optimistic streaming flag so we don't
          // show a perpetual typing indicator (the turn_done event would
          // otherwise be the only thing to clear it, and it may have fired
          // before we subscribed).
          if (streamingRef.current && !activeTurnSessionIdRef.current && mapped.some((m) => m.role === "assistant")) {
            setStreaming(false);
            setStatusLabel(null);
          }
          // Fire-and-forget after a short debounce: pre-warm only if the user
          // is still on this thread after rapid A -> B -> C switching.
          const warmSessionId = resp.session_id ?? sessionId;
          window.setTimeout(() => {
            if (
              activeSessionRef.current === warmSessionId ||
              activeSessionAliasesRef.current.has(warmSessionId)
            ) {
              void api.warmSession(warmSessionId).catch(() => {});
            }
          }, 400);
        })
        .catch(() => setError("Failed to load conversation history."))
        .finally(() => setLoadingHistory(false));
    }
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    rememberLocalTurn(activeSessionRef.current, chatMessages);
  }, [chatMessages]);

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
  }, []);

  const disableSafeMode = useCallback(() => {
    const sid = activeSessionRef.current;
    persistSafeMode(sid, false);
    safeModeRef.current = false;
    setSafeMode(false);
    setSafeModeNotice(null);
    rememberRenderHealth(sid, false);
  }, []);

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

  const finalizeAssistant = useCallback(() => {
    setChatMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "assistant" && last.streaming) {
        next[next.length - 1] = { ...last, streaming: false };
      }
      return next;
    });
  }, []);

  const flushTokenBuffer = useCallback(() => {
    rafPendingRef.current = null;
    const buffered = tokenBufferRef.current.join("");
    tokenBufferRef.current = [];
    if (!buffered) return;
    setChatMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "assistant" && last.streaming) {
        const windowed = windowLiveStream({
          content: last.content,
          totalChars: last.liveTotalChars ?? last.content.length,
          fenceCount: last.liveFenceCount ?? 0,
        }, buffered);
        streamTextCharsRef.current = Math.max(streamTextCharsRef.current, windowed.totalChars);
        next[next.length - 1] = {
          ...last,
          content: windowed.content,
          liveTotalChars: windowed.totalChars,
          liveOmittedChars: windowed.omittedChars,
          liveFenceCount: windowed.fenceCount,
          renderRevision: (last.renderRevision ?? 0) + 1,
        };
      } else {
        const windowed = snapshotLiveStream(buffered);
        streamTextCharsRef.current = Math.max(streamTextCharsRef.current, windowed.totalChars);
        next.push({ id: nid(), role: "assistant", content: windowed.content, streaming: true,
          liveTotalChars: windowed.totalChars, liveOmittedChars: windowed.omittedChars,
          liveFenceCount: windowed.fenceCount, renderRevision: 1 });
      }
      return next;
    });
  }, []);

  const syncLiveAssistantSnapshot = useCallback((text: string, revision?: number | null, start = 0) => {
    if (start > 0) {
      if (!text) return false;
      if (flushTimerRef.current !== null) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      if (rafPendingRef.current !== null) {
        cancelAnimationFrame(rafPendingRef.current);
        rafPendingRef.current = null;
      }
      tokenBufferRef.current = [];

      const nextRevision = typeof revision === "number" ? revision : streamRevisionRef.current + 1;
      const nextChars = start + text.length;
      const canAppend = streamTextCharsRef.current === start;
      streamRevisionRef.current = nextRevision;
      streamTextCharsRef.current = Math.max(streamTextCharsRef.current, nextChars);
      lastTokenAtRef.current = Date.now();
      setChatMessages((prev) => {
        const next = [...prev];
        for (let i = next.length - 1; i >= 0; i--) {
          const msg = next[i];
          if (msg.role !== "assistant") continue;
          const windowed = canAppend
            ? windowLiveStream({
                content: msg.content,
                totalChars: msg.liveTotalChars ?? msg.content.length,
                fenceCount: msg.liveFenceCount ?? 0,
              }, text, nextChars)
            : snapshotLiveStream(text, nextChars);
          next[i] = {
            ...msg,
            content: windowed.content,
            liveTotalChars: windowed.totalChars,
            liveOmittedChars: windowed.omittedChars,
            liveFenceCount: windowed.fenceCount,
            streaming: true,
            renderRevision: nextRevision > 0 ? nextRevision : (msg.renderRevision ?? 0) + 1,
          };
          return next;
        }
        const windowed = snapshotLiveStream(text, nextChars);
        next.push({ id: nid(), role: "assistant", content: windowed.content, streaming: true,
          liveTotalChars: windowed.totalChars, liveOmittedChars: windowed.omittedChars,
          liveFenceCount: windowed.fenceCount, renderRevision: nextRevision });
        return next;
      });
      return true;
    }

    const currentState = { revision: streamRevisionRef.current, textChars: streamTextCharsRef.current };
    if (!shouldApplyStreamRenderSnapshot(currentState, { text, revision })) return false;

    if (flushTimerRef.current !== null) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    if (rafPendingRef.current !== null) {
      cancelAnimationFrame(rafPendingRef.current);
      rafPendingRef.current = null;
    }
    tokenBufferRef.current = [];

    const nextState = applyStreamRenderSnapshotState(currentState, { text, revision });
    streamRevisionRef.current = nextState.revision;
    streamTextCharsRef.current = nextState.textChars;
    lastTokenAtRef.current = Date.now();
    let applied = false;
    setChatMessages((prev) => {
      const next = [...prev];
      for (let i = next.length - 1; i >= 0; i--) {
        const msg = next[i];
        if (msg.role !== "assistant") continue;
        const windowed = snapshotLiveStream(text, nextState.textChars);
        if (msg.content === windowed.content && msg.liveTotalChars === windowed.totalChars) return prev;
        next[i] = {
          ...msg,
          content: windowed.content,
          liveTotalChars: windowed.totalChars,
          liveOmittedChars: windowed.omittedChars,
          liveFenceCount: windowed.fenceCount,
          streaming: true,
          renderRevision: nextState.revision > 0 ? nextState.revision : (msg.renderRevision ?? 0) + 1,
        };
        applied = true;
        return next;
      }
      const windowed = snapshotLiveStream(text, nextState.textChars);
      next.push({
        id: nid(),
        role: "assistant",
        content: windowed.content,
        liveTotalChars: windowed.totalChars,
        liveOmittedChars: windowed.omittedChars,
        liveFenceCount: windowed.fenceCount,
        streaming: true,
        renderRevision: nextState.revision > 0 ? nextState.revision : 1,
      });
      applied = true;
      return next;
    });
    return applied;
  }, []);

  // Accumulate tokens and flush at a controlled cadence instead of on every
  // animation frame. Long markdown responses can otherwise spend the whole
  // stream re-rendering the live assistant row.
  const appendToken = useCallback((token: string) => {
    tokenBufferRef.current.push(token);
    const tokenNow = Date.now();
    if (tokenNow - lastTokenAtRef.current >= 250) lastTokenAtRef.current = tokenNow;
    if (flushTimerRef.current === null && rafPendingRef.current === null) {
      flushTimerRef.current = window.setTimeout(() => {
        flushTimerRef.current = null;
        rafPendingRef.current = requestAnimationFrame(flushTokenBuffer);
      }, liveStreamFlushInterval(streamTextCharsRef.current + token.length));
    }
  }, [flushTokenBuffer]);

  const flushReasoningBuffer = useCallback(() => {
    reasoningRafRef.current = null;
    const buffered = reasoningBufferRef.current;
    const bufferedChars = reasoningBufferedCharsRef.current;
    reasoningBufferRef.current = "";
    reasoningBufferedCharsRef.current = 0;
    if (!buffered) return;
    setChatMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "reasoning") {
        const windowed = appendBoundedText({
          text: last.text,
          totalChars: last.totalChars ?? last.text.length,
          omittedChars: last.omittedChars ?? 0,
        }, buffered, REASONING_WINDOW_CHARS);
        windowed.totalChars += Math.max(0, bufferedChars - buffered.length);
        windowed.omittedChars = Math.max(0, windowed.totalChars - windowed.text.length);
        next[next.length - 1] = { ...last, text: windowed.text,
          totalChars: windowed.totalChars, omittedChars: windowed.omittedChars };
      } else {
        const windowed = boundText(buffered, REASONING_WINDOW_CHARS, bufferedChars);
        next.push({ id: nid(), role: "reasoning", text: windowed.text,
          totalChars: windowed.totalChars, omittedChars: windowed.omittedChars });
      }
      return next;
    });
  }, []);

  // Accumulate reasoning deltas and flush once per animation frame, mirroring tokens.
  const appendReasoning = useCallback((text: string) => {
    reasoningBufferRef.current = `${reasoningBufferRef.current}${text}`.slice(-REASONING_WINDOW_CHARS);
    reasoningBufferedCharsRef.current += text.length;
    if (reasoningRafRef.current === null) {
      reasoningRafRef.current = requestAnimationFrame(flushReasoningBuffer);
    }
  }, [flushReasoningBuffer]);

  // Flush buffered tokens AND reasoning immediately — call before appending a tool
  // row, finalizing, or ending a turn so ordering and the final deltas are preserved.
  const flushPendingStream = useCallback(() => {
    if (flushTimerRef.current !== null) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    if (rafPendingRef.current !== null) {
      cancelAnimationFrame(rafPendingRef.current);
      flushTokenBuffer();
    } else if (tokenBufferRef.current.length > 0) {
      flushTokenBuffer();
    }
    if (reasoningRafRef.current !== null) {
      cancelAnimationFrame(reasoningRafRef.current);
      flushReasoningBuffer();
    }
  }, [flushTokenBuffer, flushReasoningBuffer]);

  // Re-sync turn state after a suspected lost event (SSE reconnect or stall).
  // Polls the backend's authoritative turn-status; if the turn already finished
  // we flush + finalize the assistant bubble and reload history so nothing is
  // lost. If it's still running we surface a gentle "still working" status
  // instead of leaving the UI frozen on a stale typing indicator.
  const resyncTurnState = useCallback(async (options: { allowIdle?: boolean } = {}) => {
    const sid = activeSessionRef.current;
    if (!sid || (!streamingRef.current && !options.allowIdle) || resyncInFlightRef.current) return;
    const recoverySeq = sessionRecoverySeqRef.current;
    resyncInFlightRef.current = true;
    setRecoveryPollCount((count) => count + 1);
    try {
      const status = await api.getTurnStatus(sid);
      debugChatRecovery("resync-turn-status", status.diagnostics ?? status);
      if (!isCurrentSessionResponse(
        recoverySeq,
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
        // Turn finished while we weren't listening — finalize from history.
        flushPendingStream();
        finalizeAssistant();
        setStreaming(false);
        setStatusLabel(null);
        try {
          const resp = await api.getSessionMessages(sid, HISTORY_PAGE);
          if (!isCurrentSessionResponse(recoverySeq, sid, resp.session_id)) return;
          rememberActiveSessionAliases(sid, resp.session_id);
          const mapped = sessionMessagesToChat(
            resp.messages.filter(
              (m) => m.role === "user" || m.role === "assistant" || m.role === "tool",
            ),
          );
          const hasAssistant = mapped.some((m) => m.role === "assistant" && m.content.trim());
          setChatMessages((prev) => mergeSyncedMessages(
            mapped,
            prev,
            resp.session_id ?? sid,
            { preferSyncedAssistants: true, syncedComplete: !(resp.has_earlier ?? false) },
          ));
          if (wasStreaming && !hasAssistant) {
            appendRecoveredStaleTurnNote("The previous response stopped before Spark saved an assistant reply. You can retry this message.");
          }
        } catch {
          /* keep whatever we have locally */
          if (wasStreaming) {
            appendRecoveredStaleTurnNote("Spark lost the live response state while reconnecting. You can retry or send a follow-up.");
          }
        }
      } else {
        // Still running — reset the stall clock and reassure the user.
        const snapshotSessionId = status.active_turn_session_id ?? sid;
        activeTurnSessionIdRef.current = snapshotSessionId;
        lastEventAtRef.current = Date.now();
        setTurnState(recoverTurnStateFromBackend({
          turnActive: true,
          phase: status.phase,
          state: status.state,
          interruptRequested: status.interrupt_requested,
        }));
        setStatusLabel(
          backendTurnStatusLabel({
            turnActive: true,
            phase: status.phase,
            state: status.state,
            status: status.status,
            idleForSeconds: status.idle_for_seconds,
          }) ?? MODEL_LOADING_LABEL,
        );
        try {
          const snapshot = await api.getStreamSnapshot(
            snapshotSessionId,
            streamTextCharsRef.current > 0 ? { afterChars: streamTextCharsRef.current } : {},
          );
          debugChatRecovery("resync-stream-snapshot", snapshot.diagnostics ?? snapshot);
          if (!isCurrentSessionResponse(
            recoverySeq,
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
            syncLiveAssistantSnapshot(
              snapshot.stream_text,
              snapshot.stream_revision,
              snapshot.stream_text_start ?? 0,
            );
          }
          if (!snapshot.turn_active) {
            activeTurnSessionIdRef.current = null;
            flushPendingStream();
            finalizeAssistant();
            setStreaming(false);
            setStatusLabel("Finalizing from saved history…");
            try {
              const resp = await api.getSessionMessages(snapshot.latest_session_id ?? snapshotSessionId, HISTORY_PAGE);
              if (!isCurrentSessionResponse(recoverySeq, sid, resp.session_id)) return;
              rememberActiveSessionAliases(sid, resp.session_id);
              const mapped = sessionMessagesToChat(
                resp.messages.filter(
                  (m) => m.role === "user" || m.role === "assistant" || m.role === "tool",
                ),
              );
              setChatMessages((prev) => mergeSyncedMessages(
                mapped,
                prev,
                resp.session_id ?? sid,
                { preferSyncedAssistants: true, syncedComplete: !(resp.has_earlier ?? false) },
              ));
            } catch {
              /* final history recovery is best-effort */
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
    flushPendingStream,
    finalizeAssistant,
    setStreaming,
    syncLiveAssistantSnapshot,
    isCurrentSessionResponse,
    rememberActiveSessionAliases,
    appendRecoveredStaleTurnNote,
  ]);

  resyncTurnStateRef.current = resyncTurnState;

  useEventBus((env) => {
    // Synthetic local event from the SSE bus reopening after a drop. Events
    // emitted during the gap (possibly a whole turn_done) may have been missed,
    // so reconcile against the backend's turn-status.
    if (env.topic === BUS_RECONNECTED_TOPIC) {
      setSseReconnectCount((count) => count + 1);
      const result = consumeRecoverySignal(recoverySignalBudgetRef.current, Date.now());
      recoverySignalBudgetRef.current = result.budget;
      if (result.allowed) void resyncTurnState({ allowIdle: true });
      return;
    }
    const sid = env.session_id ?? undefined;
    if (!sid || !activeSessionAliasesRef.current.has(sid)) return;
    if (env.topic === BUS_GAP_TOPIC) {
      const result = consumeRecoverySignal(recoverySignalBudgetRef.current, Date.now());
      recoverySignalBudgetRef.current = result.budget;
      if (result.allowed) void resyncTurnState({ allowIdle: true });
      return;
    }
    const eventNow = Date.now();
    if (eventNow - lastEventAtRef.current >= 250) lastEventAtRef.current = eventNow;
    const data = env.data as Record<string, unknown>;

    switch (env.topic) {
      case "chat.token": {
        const t = data.t;
        if (typeof t === "string" && t) appendToken(t);
        // A token stream can deliver thousands of events per second. Do not
        // enqueue an identical React state update for every event.
        if (turnStateRef.current !== "streaming") {
          const next = nextChatTurnState(turnStateRef.current, { type: "token" });
          turnStateRef.current = next;
          setTurnState(next);
        }
        break;
      }
      case "chat.tool_start": {
        flushPendingStream();
        finalizeAssistant();
        setTurnState((prev) => nextChatTurnState(prev, { type: "tool_start" }));
        setChatMessages((prev) => [
          ...prev,
          {
            id: nid(),
            role: "tool",
            toolId: String(data.id ?? ""),
            name: String(data.name ?? "tool"),
            args: (data.args as Record<string, unknown>) ?? {},
            done: false,
            startedAt: typeof data.started_at === "number" ? data.started_at : typeof data.ts === "number" ? data.ts : undefined,
          },
        ]);
        setStatusLabel(`Tool: ${String(data.name ?? "")}`);
        break;
      }
      case "chat.tool_end": {
        const tid = String(data.id ?? "");
        setTurnState((prev) => nextChatTurnState(prev, { type: "tool_end" }));
        setChatMessages((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i--) {
            const row = next[i];
            if (row.role === "tool" && row.toolId === tid) {
              const preview = String(data.result_preview ?? data.result ?? "");
              next[i] = {
                ...row,
                result: preview,
                resultTruncated: Boolean(data.result_truncated ?? data.truncated) || undefined,
                done: true,
                endedAt: typeof data.ended_at === "number" ? data.ended_at : typeof data.ts === "number" ? data.ts : undefined,
                durationSeconds: typeof data.duration_seconds === "number" ? data.duration_seconds : undefined,
              };
              break;
            }
          }
          return next;
        });
        break;
      }
      case "chat.reasoning": {
        const text = String((data as { text?: string }).text ?? "");
        if (text) appendReasoning(text);
        break;
      }
      case "chat.subagent.created": {
        const run = (data as { subagent?: { name?: string; task?: string } }).subagent ?? {};
        const name = typeof run.name === "string" && run.name.trim() ? run.name.trim() : "sub-agent";
        const task = typeof run.task === "string" && run.task.trim() ? `: ${run.task.trim().slice(0, 140)}` : "";
        setChatMessages((prev) => [...prev, { id: nid(), role: "note", text: `Created ${name}${task}` }]);
        setStatusLabel(`Created ${name}`);
        break;
      }
      case "chat.status": {
        const msg = String((data as { message?: string }).message ?? "");
        if (msg) setStatusLabel(msg);
        break;
      }
      case "chat.approval_requested": {
        flushPendingStream();
        finalizeAssistant();
        const approval = (data as { approval?: Record<string, unknown> }).approval ?? {};
        setChatMessages((prev) => [...prev, { id: nid(), role: "approval", approval }]);
        setStatusLabel("Waiting for approval…");
        break;
      }
      case "chat.approval_resolved":
        setStatusLabel(null);
        setChatMessages((prev) =>
          prev.map((m) => (m.role === "approval" ? { ...m, resolved: true } : m)),
        );
        break;
      case "chat.session_migrated": {
        const oldId = String((data as { old_session_id?: string }).old_session_id ?? "");
        const newId = String((data as { new_session_id?: string }).new_session_id ?? "");
        rememberActiveSessionAliases(oldId, newId);
        setTurnState((prev) => nextChatTurnState(prev, { type: "session_migrated" }));
        if (newId && newId !== activeSessionRef.current) {
          activeSessionRef.current = newId;
          setActiveSessionId(newId);
          onSessionUpdated?.(newId);
          // Inline marker so the user understands why the agent may suddenly
          // recall less detail about earlier work in this thread.
          setChatMessages((prev) => [
            ...prev,
            {
              id: nid(),
              role: "note",
              text: "Earlier conversation was summarized to free context space — the assistant may not recall fine-grained details from before this point.",
            },
          ]);
        }
        break;
      }
      case "chat.compaction": {
        const status = String((data as { status?: string }).status ?? "");
        if (status === "failed") {
          const message = String((data as { message?: string }).message ?? "");
          setChatMessages((prev) => [
            ...prev,
            {
              id: nid(),
              role: "note",
              text: message || "Context compression failed. The transcript was preserved, and you can retry this message.",
            },
          ]);
          setStatusLabel(null);
        }
        break;
      }
      case "chat.interrupted": {
        flushPendingStream();
        finalizeAssistant();
        const msg = (data as { message?: string }).message;
        const phase = (data as { phase?: string }).phase === "redirecting" ? "redirecting" : "stopping";
        setChatMessages((prev) => [
          ...prev,
          { id: nid(), role: "note", text: msg ? `Interrupted: ${msg}` : "Interrupted." },
        ]);
        setTurnState(nextChatTurnState(turnStateRef.current, { type: "interrupt_requested", redirect: phase === "redirecting" }));
        setStatusLabel(phase === "redirecting" ? "Redirecting…" : "Stopping…");
        void resyncTurnState();
        break;
      }
      case "chat.turn_done": {
        debugChatRecovery("turn-done", (data as { diagnostics?: unknown }).diagnostics ?? data);
        // Flush any remaining buffered tokens before finalizing
        flushPendingStream();
        finalizeAssistant();
        setTurnState((prev) => nextChatTurnState(prev, { type: "turn_done" }));
        setStatusLabel(null);
        // Extract token/cost stats from the richer payload
        {
          const tokens = data.tokens as Record<string, number> | undefined;
          const cost = typeof data.cost_usd === "number" ? data.cost_usd : undefined;
          const model = typeof data.model === "string" ? data.model : undefined;
          const interrupted = Boolean((data as { interrupted?: boolean }).interrupted);
          const finalAssistantPresent = Boolean((data as { final_assistant_present?: boolean }).final_assistant_present);
          const backendErrorClass = typeof (data as { backend_error_class?: unknown }).backend_error_class === "string"
            ? String((data as { backend_error_class?: string }).backend_error_class)
            : "";
          setSessionStats((prev) => ({
            model: model ?? prev.model,
            inputTokens: (prev.inputTokens ?? 0) + (tokens?.input ?? 0),
            outputTokens: (prev.outputTokens ?? 0) + (tokens?.output ?? 0),
            cacheReadTokens: (prev.cacheReadTokens ?? 0) + (tokens?.cache_read ?? 0),
            cacheWriteTokens: (prev.cacheWriteTokens ?? 0) + (tokens?.cache_write ?? 0),
            costUsd: (prev.costUsd ?? 0) + (cost ?? 0),
            turnCount: (prev.turnCount ?? 0) + 1,
          }));
          // Attach this turn's usage to the just-finalized assistant message.
          const turnTokens = (tokens?.input ?? 0) + (tokens?.output ?? 0);
          if (turnTokens > 0 || cost != null) {
            setChatMessages((prev) => {
              for (let i = prev.length - 1; i >= 0; i--) {
                const m = prev[i];
                if (m.role === "assistant") {
                  const next = [...prev];
                  next[i] = { ...m, usage: { totalTokens: turnTokens, costUsd: cost } };
                  return next;
                }
              }
              return prev;
            });
          }
          if (!interrupted && (!finalAssistantPresent || backendErrorClass)) {
            setChatMessages((prev) => [
              ...prev,
              {
                id: nid(),
                role: "note",
                text: backendErrorClass
                  ? `Turn ended with a backend error (${backendErrorClass}). You can retry this message.`
                  : "Turn ended without a saved assistant response. You can retry this message.",
              },
            ]);
          }
        }
        const cur = activeSessionRef.current;
        if (cur) {
          const doneSessionId = typeof data.session_id === "string" ? data.session_id : undefined;
          rememberActiveSessionAliases(cur, sid, doneSessionId);
          onSessionUpdated?.(cur);
          const finalHistorySessionId = doneSessionId ?? cur;
          const applyFinalHistory = (resp: Awaited<ReturnType<typeof api.getSessionMessages>>) => {
            const current = activeSessionRef.current;
            const aliases = activeSessionAliasesRef.current;
            const responseSessionId = resp.session_id ?? finalHistorySessionId;
            if (
              !current ||
              (
                current !== cur &&
                current !== finalHistorySessionId &&
                current !== responseSessionId &&
                !aliases.has(finalHistorySessionId) &&
                !aliases.has(responseSessionId)
              )
            ) return;
            rememberActiveSessionAliases(cur, finalHistorySessionId, responseSessionId);
            const mapped = sessionMessagesToChat(
              resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
            );
            setChatMessages((prev) => mergeSyncedMessages(
              mapped,
              prev,
              responseSessionId,
              { preferSyncedAssistants: true, syncedComplete: !(resp.has_earlier ?? false) },
            ));
          };
          void api
            .getSessionMessages(finalHistorySessionId, HISTORY_PAGE)
            .then((resp) => {
              applyFinalHistory(resp);
              window.setTimeout(() => {
                void api
                  .getSessionMessages(finalHistorySessionId, HISTORY_PAGE)
                  .then(applyFinalHistory)
                  .catch(() => {});
              }, 500);
            })
            .catch(() => {});
          // Sync sessionIdx values on recent user messages for retry/fork.
          // Fetch only the tail (last 20) to avoid transmitting the full history
          // every turn. Patch sessionIdx in-place rather than replacing the list.
          setTimeout(() => {
            void api
              .getSessionMessages(finalHistorySessionId, 20)
              .then((resp) => {
                const current = activeSessionRef.current;
                const responseSessionId = resp.session_id ?? finalHistorySessionId;
                if (
                  !current ||
                  (
                    current !== cur &&
                    current !== finalHistorySessionId &&
                    current !== responseSessionId &&
                    !activeSessionAliasesRef.current.has(finalHistorySessionId) &&
                    !activeSessionAliasesRef.current.has(responseSessionId)
                  )
                ) return;
                rememberActiveSessionAliases(cur, finalHistorySessionId, responseSessionId);
                const tail = resp.messages.filter((m) => m.role === "user");
                if (tail.length === 0) return;
                const tailByContent = new Map(tail.map((m, i) => [
                  m.content ?? "",
                  m.message_index ?? resp.messages.indexOf(tail[i]),
                ]));
                setChatMessages((prev) => {
                  let changed = false;
                  const next = prev.map((m) => {
                    if (m.role !== "user") return m;
                    if (m.sessionIdx != null) return m;
                    const newIdx = tailByContent.get(m.content);
                    if (newIdx != null && newIdx !== m.sessionIdx) {
                      changed = true;
                      return { ...m, sessionIdx: newIdx };
                    }
                    return m;
                  });
                  return changed ? next : prev;
                });
              })
              .catch(() => {});
          }, 500);
        }
        break;
      }
      default:
        break;
    }
  });

  // One recovery poller covers both active stalls and idle app-resume checks.
  // It stays quiet while SSE is fresh and pauses while the window is hidden.
  useEffect(() => {
    if (!activeSessionId) return;
    if (!lastEventAtRef.current) lastEventAtRef.current = Date.now();
    if (streaming && !lastTokenAtRef.current) lastTokenAtRef.current = Date.now();
    const tick = () => {
      const decision = decideRecoveryPoll({
        streaming: streamingRef.current,
        hidden: typeof document !== "undefined" && document.hidden,
        now: Date.now(),
        lastEventAt: lastEventAtRef.current,
        lastTokenAt: lastTokenAtRef.current,
        lastIdlePollAt: lastIdleRecoveryPollAtRef.current,
      });
      lastIdleRecoveryPollAtRef.current = decision.nextIdlePollAt;
      if (decision.statusLabel) {
        setStatusLabel(decision.statusLabel);
      }
      if (decision.poll) {
        const result = consumeRecoverySignal(recoverySignalBudgetRef.current, Date.now());
        recoverySignalBudgetRef.current = result.budget;
        if (result.allowed) void resyncTurnState({ allowIdle: !streamingRef.current });
      }
    };
    const handleVisibility = () => {
      if (document.hidden) return;
      const result = consumeRecoverySignal(recoverySignalBudgetRef.current, Date.now());
      recoverySignalBudgetRef.current = result.budget;
      if (result.allowed) void resyncTurnState({ allowIdle: !streamingRef.current });
    };
    const interval = setInterval(tick, 2_000);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [activeSessionId, streaming, resyncTurnState]);

  const sendMessage = async () => {
    const text = input.trim();
    if (!text) return;

    // While a turn is streaming, a submit becomes a redirect: interrupt the
    // running turn and hand it the new message (read on the next loop iter).
    if (streaming) {
      const sid = activeTurnSessionIdRef.current ?? activeSessionId;
      if (!sid) return;
      setChatMessages((prev) => [
        ...prev,
        { id: nid(), role: "user", content: text, redirect: true },
      ]);
      setTurnState(nextChatTurnState(turnStateRef.current, { type: "interrupt_requested", redirect: true }));
      setStatusLabel("Redirecting…");
      try {
        await api.interruptConversation(sid, text);
        setInput("");
      } catch {
        setStatusLabel("Redirect requested; waiting for backend state…");
        void resyncTurnState();
      }
      return;
    }

    setInput("");
    setError(null);
    const itemsToSend = contextItems;
    // Drop one-turn items after send; keep pinned items
    setContextItems((prev) => prev.filter((i) => i.scope === "pinned"));
    setChatMessages((prev) => [
      ...prev,
      { id: nid(), role: "user", content: text, contextItems: itemsToSend.length ? itemsToSend : undefined },
    ]);

    // /feedback is handled entirely in the frontend — inject the form immediately,
    // send to backend only to prevent agent fallthrough (backend returns "").
    if (text.trim() === "/feedback") {
      setChatMessages((prev) => [...prev, { id: nid(), role: "feedback_form" as const }]);
    }

    setTurnState(nextChatTurnState(turnStateRef.current, { type: "submit" }));
    setStatusLabel(MODEL_LOADING_LABEL);
    followStreamRef.current = true;
    streamRevisionRef.current = 0;
    streamTextCharsRef.current = 0;
    scrollStateRef.current = reduceChatScrollState(scrollStateRef.current, {
      type: "jump-to-bottom",
      itemCount: chatMessages.length + 1,
    });
    setDetachedFromBottom(false);

    // Yield to the browser paint cycle so the stop button renders
    // before we block on the API call.
    await new Promise((r) => setTimeout(r, 0));

    try {
      let sid = activeSessionId;

      if (!sid) {
        if (workspaceSlug) {
          const resp = await api.startWorkspaceConversation(workspaceSlug, text, undefined, itemsToSend);
          sid = resp.session_id;
          activeSessionRef.current = sid;
          setActiveSessionId(sid);
          onSessionCreated?.(sid, text, { source: resp.source, projectSlug: workspaceSlug });
        } else {
          const resp = await api.postConversation(text, undefined, itemsToSend);
          sid = resp.session_id;
          activeSessionRef.current = sid;
          setActiveSessionId(sid);
          onSessionCreated?.(sid, text);
        }
      } else {
        activeSessionRef.current = sid;
        const resp = await api.postConversationMessage(sid, text, itemsToSend);
        if (resp.session_id && resp.session_id !== sid) {
          sid = resp.session_id;
          activeSessionRef.current = sid;
          setActiveSessionId(sid);
          onSessionCreated?.(sid, text);
        }
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg.replace(/^\d+:\s*/, ""));
      setChatMessages((prev) => prev.filter((m, i) => i < prev.length - 1 || m.role !== "user"));
      setStreaming(false);
      setStatusLabel(null);
    }
  };

  const stop = async () => {
    const sid = activeTurnSessionIdRef.current ?? activeSessionId;
    if (!sid) return;
    if (turnStateRef.current === "stopping" || turnStateRef.current === "redirecting") return;
    setTurnState(nextChatTurnState(turnStateRef.current, { type: "interrupt_requested" }));
    setStatusLabel("Stopping…");
    try {
      await api.interruptConversation(sid);
    } catch {
      setStatusLabel("Stop requested; waiting for backend state…");
      void resyncTurnState();
    }
  };

  // Use refs for values that change so useCallback deps stay empty → stable identities
  const onSessionCreatedRef = useRef(onSessionCreated);
  onSessionCreatedRef.current = onSessionCreated;

  const doFork = useCallback(async (fromSessionIdx?: number) => {
    const sid = activeSessionRef.current;
    if (!sid) return;
    try {
      const r = await api.forkConversation(sid, fromSessionIdx);
      setActiveSessionId(r.session_id);
      activeSessionRef.current = r.session_id;
      onSessionCreatedRef.current?.(r.session_id);
      setChatMessages([]);
      setLoadingHistory(true);
      const resp = await api.getSessionMessages(r.session_id);
      setChatMessages(
        sessionMessagesToChat(
          resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  const doRetry = useCallback(async (sessionIdx: number, edited?: string) => {
    const sid = activeSessionRef.current;
    if (!sid || streamingRef.current) return;
    try {
      await api.retryConversation(sid, sessionIdx, edited);
      setStreaming(true);
      setStatusLabel(MODEL_LOADING_LABEL);
      followStreamRef.current = true;
      streamRevisionRef.current = 0;
      streamTextCharsRef.current = 0;
      scrollStateRef.current = reduceChatScrollState(scrollStateRef.current, {
        type: "jump-to-bottom",
      });
      setDetachedFromBottom(false);
      setChatMessages((prev) => {
        const next = [...prev];
        while (next.length > 0) {
          const last = next[next.length - 1];
          if (last.role === "assistant" || last.role === "tool" || last.role === "reasoning" || last.role === "note") {
            next.pop();
            continue;
          }
          if (last.role === "user" && last.sessionIdx === sessionIdx) {
            if (edited != null) {
              next[next.length - 1] = { ...last, content: edited };
            }
            break;
          }
          break;
        }
        return next;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [setStreaming]);

  const reloadLatestTranscript = useCallback(async () => {
    const sid = activeSessionRef.current;
    if (!sid) return;
    setLoadingHistory(true);
    try {
      const resp = await api.getSessionMessages(sid, HISTORY_PAGE);
      rememberActiveSessionAliases(sid, resp.session_id);
      const mapped = sessionMessagesToChat(
        resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
      );
      setChatMessages((prev) => mergeSyncedMessages(
        mapped,
        prev,
        resp.session_id ?? sid,
        { preferSyncedAssistants: true, syncedComplete: !(resp.has_earlier ?? false) },
      ));
      setHasEarlier(resp.has_earlier ?? false);
      setStatusLabel(streamingRef.current ? statusLabel ?? MODEL_LOADING_LABEL : null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoadingHistory(false);
    }
  }, [HISTORY_PAGE, rememberActiveSessionAliases, statusLabel]);

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
  }, [recoveryPollCount, sseReconnectCount]);

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
        streamRevisionRef.current = 0;
        streamTextCharsRef.current = 0;
        await api.postConversationMessage(sid, text);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      void resyncTurnStateRef.current?.({ allowIdle: true });
    } finally {
      setRecoveryActionBusy(null);
    }
  }, []);

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
  }, [conversationDiagnostics, refreshConversationDiagnostics]);

  const runRecoveryAction = useCallback(async (id: RecoveryActionId) => {
    if (recoveryActionBusy) return;
    setRecoveryActionBusy(id);
    try {
      if (id === "reload") {
        await reloadLatestTranscript();
      } else if (id === "retry") {
        if (latestUserMessage?.sessionIdx != null) await doRetry(latestUserMessage.sessionIdx);
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
    doRetry,
    latestUserMessage,
    recoveryActionBusy,
    reloadLatestTranscript,
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

  const shouldShowRecoveryPanel = Boolean(activeSessionId) && (diagnosticsOpen || turnState === "stalled");

  useEffect(() => {
    if (!shouldShowRecoveryPanel) return;
    void refreshConversationDiagnostics();
  }, [refreshConversationDiagnostics, shouldShowRecoveryPanel, turnState]);

  const submitApproval = useCallback(async (choice: "once" | "session" | "always" | "deny") => {
    const sid = activeSessionRef.current;
    if (!sid) return;
    setApprovalBusy(true);
    try {
      await api.submitConversationApproval(sid, choice);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApprovalBusy(false);
    }
  }, []);

  const copyText = useCallback((t: string) => {
    void navigator.clipboard.writeText(t);
  }, []);

  const fetchExactAssistant = useCallback(async (msg: AssistantMsg) => {
    if (!msg.liveOmittedChars) return msg.content;
    const cached = exactAssistantContentRef.current.get(msg.id);
    if (cached != null) return cached;
    const sid = activeSessionRef.current;
    if (!sid) return msg.content;
    const response = await api.getSessionMessages(sid);
    const exact = exactAssistantContent(response.messages, msg.id) ?? msg.content;
    exactAssistantContentRef.current.set(msg.id, exact);
    return exact;
  }, []);

  const copyAssistant = useCallback((msg: AssistantMsg) => {
    const sid = activeSessionRef.current;
    if (!msg.liveOmittedChars || !sid) {
      void navigator.clipboard.writeText(msg.content);
      return;
    }
    void copyExactAssistantContent({
      renderedId: msg.id,
      visibleFallback: msg.content,
      loadMessages: async () => (await api.getSessionMessages(sid)).messages,
      writeText: (content) => navigator.clipboard.writeText(content),
    })
      .catch(() => navigator.clipboard.writeText(msg.content));
  }, []);

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
  }, []);

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
  const handleEdit = useCallback((idx: number, text: string) => {
    setEditingUser({ sessionIdx: idx, text });
  }, []);
  const handleRetry = useCallback((idx: number) => { void doRetry(idx); }, [doRetry]);
  const handleFork = useCallback((idx: number) => { void doFork(idx); }, [doFork]);

  const loadEarlierMessages = useCallback(async () => {
    const sid = activeSessionRef.current;
    if (!sid || loadingEarlier) return;
    const recoverySeq = sessionRecoverySeqRef.current;
    const firstMsg = chatMessages.find((m) => (m as { sessionIdx?: number }).sessionIdx != null);
    const firstId = (firstMsg as { id?: string })?.id;
    const beforeId = firstId?.startsWith("db:") ? firstId.slice(3) : firstId;
    const scrollEl = scrollContainerRef.current;
    prependScrollAnchorRef.current = scrollEl
      ? {
          scrollHeight: scrollEl.scrollHeight,
          scrollTop: scrollEl.scrollTop,
          anchorId: firstId ?? null,
        }
      : null;
    setLoadingEarlier(true);
    try {
      const resp = await api.getSessionMessages(sid, HISTORY_PAGE, beforeId);
      if (!isCurrentSessionResponse(recoverySeq, sid, resp.session_id)) return;
      rememberActiveSessionAliases(sid, resp.session_id);
      const mapped = sessionMessagesToChat(
        resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
      );
      setChatMessages((prev) => {
        const existingIds = new Set(prev.map((m) => m.id));
        const older = mapped.filter((m) => !existingIds.has(m.id));
        if (older.length === 0) return prev;
        return [...older, ...prev];
      });
      setHasEarlier(resp.has_earlier ?? false);
    } catch {
      // silently ignore
      prependScrollAnchorRef.current = null;
    } finally {
      setLoadingEarlier(false);
    }
  }, [chatMessages, loadingEarlier, HISTORY_PAGE, isCurrentSessionResponse, rememberActiveSessionAliases]);

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
    void api.getSessionMessages(sid).then((response) => {
      if (cancelled || recoverySeq !== sessionRecoverySeqRef.current) return;
      for (const message of response.messages) {
        if (message.role === "assistant" && message.id != null && message.content != null) {
          exactAssistantContentRef.current.set(`db:${message.id}`, message.content);
        }
      }
      const results: number[] = [];
      chatMessages.forEach((msg, index) => {
        const text = msg.role === "assistant"
          ? exactAssistantContentRef.current.get(msg.id) ?? msg.content
          : msg.role === "user" ? msg.content
          : msg.role === "reasoning" ? msg.text
          : "";
        if (text.toLowerCase().includes(q)) results.push(index);
      });
      setSearchMatches(results);
    }).catch(() => {
      if (exactSearchRequestKeyRef.current === requestKey) exactSearchRequestKeyRef.current = "";
    });
    return () => { cancelled = true; };
  }, [chatMessages, searchQuery]);

  // Scroll active match into view using the virtualizer
  useEffect(() => {
    if (!searchMatches.length) return;
    const idx = searchMatches[searchMatchIdx % searchMatches.length];
    virtualizer.scrollToIndex(idx, { align: "center", behavior: safeMode ? "instant" : "smooth" });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchMatchIdx, searchMatches, safeMode]);

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

  // Collapse consecutive same-name tool calls and append a typing indicator
  // synthetic entry when streaming has started but no assistant token arrived yet.
  type CollapsedItem = { msg: ChatMessage; repeatCount: number; id: string } | { msg: null; id: "typing" };
  const collapsedMessages = useMemo<CollapsedItem[]>(() => {
    const collapsed: CollapsedItem[] = [];
    for (const msg of chatMessages) {
      const prev = collapsed[collapsed.length - 1];
      if (
        msg.role === "tool" &&
        prev && prev.msg !== null && prev.msg.role === "tool" &&
        msg.name === (prev.msg as Extract<ChatMessage, { role: "tool" }>).name
      ) {
        const previousTool = prev.msg as ToolMsg;
        const previousDuration = toolDurationSeconds(previousTool);
        const currentDuration = toolDurationSeconds(msg);
        const combinedDuration =
          previousDuration !== undefined || currentDuration !== undefined
            ? (previousDuration ?? 0) + (currentDuration ?? 0)
            : undefined;
        collapsed[collapsed.length - 1] = {
          msg: {
            ...msg,
            startedAt: previousTool.startedAt ?? msg.startedAt,
            durationSeconds: combinedDuration,
          },
          repeatCount: (prev as { msg: ChatMessage; repeatCount: number; id: string }).repeatCount + 1,
          id: prev.id,
        };
      } else {
        collapsed.push({ msg, repeatCount: 0, id: msg.id });
      }
    }
    // Append typing indicator if streaming but last message isn't an active assistant bubble
    if (streaming) {
      const last = chatMessages[chatMessages.length - 1];
      const isAlreadyStreamingAssistant = last?.role === "assistant" && (last.streaming || !last.content);
      if (!isAlreadyStreamingAssistant) {
        collapsed.push({ msg: null, id: "typing" } as CollapsedItem);
      }
    }
    return collapsed;
  }, [chatMessages, streaming]);

  const liveRowIndex = useMemo(() => findLiveRowIndex(collapsedMessages), [collapsedMessages]);

  const streamingAssistantVisibleChars = useMemo(() => {
    for (let i = chatMessages.length - 1; i >= 0; i--) {
      const msg = chatMessages[i];
      if (msg.role === "assistant" && msg.streaming) return msg.content.length;
    }
    return 0;
  }, [chatMessages]);

  const estimateRowSize = useCallback((index: number) => {
    const item = collapsedMessages[index];
    if (!item || item.msg === null) return 56;
    switch (item.msg.role) {
      case "user":
        return 72;
      case "assistant":
        return estimateAssistantRowSize(
          item.msg.content,
          item.msg.liveFenceCount,
        );
      case "tool":
        return 44;
      case "reasoning":
        return 44;
      case "approval":
        return 160;
      case "feedback_form":
        return 280;
      case "note":
        return 32;
      default:
        return 80;
    }
  }, [collapsedMessages]);

  const virtualizer = useVirtualizer({
    count: collapsedMessages.length,
    getScrollElement: () => scrollContainerRef.current,
    getItemKey: (index) => collapsedMessages[index]?.id ?? index,
    estimateSize: estimateRowSize,
    overscan: safeMode ? 4 : 10,
    gap: 12,
  });

  const rowResizeObserverRef = useRef<ResizeObserver | null>(null);
  const rowResizeRafRef = useRef<number | null>(null);

  const measureRowElement = useCallback((el: HTMLDivElement | null) => {
    if (!el) return;
    rowResizeObserverRef.current?.observe(el);
    const index = Number(el.dataset.index);
    const item = collapsedMessages[index];
    if (shouldSkipRowMeasurement(item, index, liveRowIndex, safeMode)) {
      return;
    }
    virtualizer.measureElement(el);
  }, [collapsedMessages, liveRowIndex, safeMode, virtualizer]);

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
  }, [collapsedMessages, measureRowElement]);

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
        anchorId: firstVisibleIndex == null ? null : collapsedMessages[firstVisibleIndex]?.id ?? null,
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
  }, [activeSessionId, collapsedMessages, loadingHistory, virtualizer]);

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
    const count = collapsedMessages.length;
    const countChanged = count !== prevCountRef.current;
    const pendingPrepend = prependScrollAnchorRef.current;
    if (pendingPrepend) {
      prependScrollAnchorRef.current = null;
      prevCountRef.current = count;
      scrollStateRef.current = {
        mode: "detached",
        lastItemCount: count,
        anchorId: pendingPrepend.anchorId,
      };
      followStreamRef.current = false;
      setDetachedFromBottom(true);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const target = scrollContainerRef.current;
          if (!target) return;
          const delta = target.scrollHeight - pendingPrepend.scrollHeight;
          target.scrollTop = pendingPrepend.scrollTop + delta;
          virtualizer.measure();
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
  }, [activeSessionId, collapsedMessages.length, streamingAssistantVisibleChars, streaming, safeMode, virtualizer]);

  const virtualItems = virtualizer.getVirtualItems();
  const visibleStartIndex = virtualItems[0]?.index ?? 0;
  const visibleEndIndex = virtualItems[virtualItems.length - 1]?.index ?? visibleStartIndex;
  const timelineItems = useMemo(() => {
    const sources: TimelineSourceItem[] = collapsedMessages.map((item, index) => {
      if (item.msg === null) {
        return { id: item.id, index, role: "typing", streaming: true };
      }
      const msg = item.msg;
      if (msg.role === "tool") {
        return {
          id: item.id,
          index,
          role: "tool",
          done: msg.done,
          resultTruncated: msg.resultTruncated,
          hasError: typeof msg.result === "string" && /\b(error|failed|traceback)\b/i.test(msg.result),
        };
      }
      return {
        id: item.id,
        index,
        role: msg.role === "feedback_form" ? "feedback" : msg.role,
        streaming: msg.role === "assistant" ? msg.streaming : false,
      };
    });
    return buildTimelineMinimapItems(sources);
  }, [collapsedMessages]);

  const jumpToIndex = useCallback((index: number, align: "start" | "center" | "end" = "center") => {
    if (collapsedMessages.length === 0) return;
    const nextIndex = Math.max(0, Math.min(index, collapsedMessages.length - 1));
    scrollStateRef.current = align === "end"
      ? reduceChatScrollState(scrollStateRef.current, { type: "jump-to-bottom", itemCount: collapsedMessages.length })
      : scrollStateRef.current;
    virtualizer.scrollToIndex(nextIndex, { align, behavior: safeMode ? "instant" : "smooth" });
    if (align === "end") {
      // Clamp until row measurements settle so the jump never lands short.
      runBottomClamp();
    }
  }, [collapsedMessages.length, runBottomClamp, safeMode, virtualizer]);

  const jumpToLatest = useCallback(() => {
    jumpToIndex(collapsedMessages.length - 1, "end");
  }, [collapsedMessages.length, jumpToIndex]);

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
            <StatusPill streaming={streaming} label={statusLabel} />
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
                onClick={() => doFork()}
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
        <div className="h-full overflow-y-auto px-4 py-5 pr-8" ref={scrollContainerRef}>
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
              const item = collapsedMessages[vItem.index];
              if (!item) return null;

              // Typing indicator synthetic item
              if (item.msg === null) {
                return (
                  <div
                    key="typing"
                    data-index={vItem.index}
                    data-row-id="typing"
                    ref={measureRowElement}
                    style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vItem.start}px)` }}
                  >
                    <div className="flex gap-2">
                      <SparkAgentAvatar />
                      <div className="rounded-lg px-3 py-2.5 text-sm bg-foreground/6">
                        <span className="flex gap-[4px] items-center">
                          <span className="h-2 w-2 rounded-full bg-foreground/40 animate-bounce [animation-delay:0ms]" />
                          <span className="h-2 w-2 rounded-full bg-foreground/40 animate-bounce [animation-delay:150ms]" />
                          <span className="h-2 w-2 rounded-full bg-foreground/40 animate-bounce [animation-delay:300ms]" />
                        </span>
                      </div>
                    </div>
                  </div>
                );
              }

              const { msg, repeatCount } = item as { msg: ChatMessage; repeatCount: number; id: string };
              let rowContent: React.ReactNode = null;

              if (msg.role === "user") {
                rowContent = (
                  <UserRow msg={msg} hasSession={!!activeSessionId}
                    streaming={streaming} onEdit={handleEdit} onRetry={handleRetry}
                    onFork={handleFork} onCopy={copyText} />
                );
              } else if (msg.role === "assistant") {
                if (!msg.content && !msg.streaming) return null;
                rowContent = (
                  <AssistantRow
                    msg={msg}
                    safeMode={safeMode}
                    defaultWrap={chatWordWrap}
                    onPromoteToBrief={activeSessionId ? handlePromoteToBrief : undefined}
                    onCopyExact={copyAssistant}
                  />
                );
              } else if (msg.role === "tool") {
                rowContent = <ToolRow msg={msg} repeatCount={repeatCount} safeMode={safeMode} onAttachPath={attachPath} onFetchFullResult={fetchFullToolResult} />;
              } else if (msg.role === "reasoning") {
                rowContent = <ReasoningRow msg={msg} isActive={streaming && vItem.index === collapsedMessages.length - 1} safeMode={safeMode} />;
              } else if (msg.role === "approval") {
                rowContent = <ApprovalRow msg={msg} disabled={approvalBusy} onChoice={submitApproval} />;
              } else if (msg.role === "note") {
                rowContent = <NoteRow msg={msg} />;
              } else if (msg.role === "feedback_form") {
                rowContent = (
                  <FeedbackRow
                    msg={msg}
                    sessionId={activeSessionId}
                    onSubmitted={(id) =>
                      setChatMessages((prev) =>
                        prev.map((m) => (m.id === id ? { ...m, submitted: true } : m)),
                      )
                    }
                  />
                );
              }

              if (rowContent === null) return null;

              return (
                <div
                  key={item.id}
                  data-index={vItem.index}
                  data-row-id={item.id}
                  ref={measureRowElement}
                  style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${vItem.start}px)` }}
                >
                  {rowContent}
                </div>
              );
            })}
            </div>
            </>
          )}
          {error && (
            <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2">
              <p className="text-xs text-destructive">{error}</p>
            </div>
          )}
        </div>
        <TimelineMinimap
          items={timelineItems}
          visibleStartIndex={visibleStartIndex}
          visibleEndIndex={visibleEndIndex}
          onJumpToIndex={jumpToIndex}
        />
        {detachedFromBottom && collapsedMessages.length > 0 && (
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
                void doRetry(sessionIdx, text);
              }}
            >
              Retry with edited message
            </Button>
          </div>
        </div>
      )}

      <SessionInfoBar stats={sessionStats} />

      {activeSessionId && <BriefPanel sessionId={activeSessionId} />}

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
