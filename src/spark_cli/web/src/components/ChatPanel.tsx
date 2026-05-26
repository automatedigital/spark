import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
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
} from "lucide-react";
// Square/Send/handleKeyDown removed — now handled by PromptBar
import { api } from "@/lib/api";
import type { SessionMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import { useEventBus } from "@/hooks/useEventBus";
import { ToolCallBubble } from "@/components/chat/ToolCallBubble";
import { ReasoningBubble } from "@/components/chat/ReasoningBubble";
import { ApprovalPrompt } from "@/components/chat/ApprovalPrompt";
import { FeedbackForm } from "@/components/chat/FeedbackForm";
import { StatusPill } from "@/components/chat/StatusPill";
import { PromptBar } from "@/components/chat/PromptBar";
import { SessionInfoBar } from "@/components/chat/SessionInfoBar";
import type { SessionStats } from "@/components/chat/SessionInfoBar";
import { MessageRowSkeleton } from "@/components/Skeleton";

let _msgId = 0;
const nid = () => `m${++_msgId}`;

type ChatMessage =
  | { id: string; role: "user"; content: string; sessionIdx?: number }
  | { id: string; role: "assistant"; content: string; streaming?: boolean }
  | {
      id: string;
      role: "tool";
      toolId: string;
      name: string;
      args: Record<string, unknown>;
      result?: string;
      done?: boolean;
      startedAt?: number;
      endedAt?: number;
    }
  | { id: string; role: "reasoning"; text: string }
  | {
      id: string;
      role: "approval";
      approval: Record<string, unknown>;
      resolved?: boolean;
    }
  | { id: string; role: "note"; text: string }
  | { id: string; role: "feedback_form"; submitted?: boolean };

interface ChatPanelProps {
  sessionId: string | null;
  onClose?: () => void;
  onBack?: () => void;
  onSessionCreated?: (id: string, initialMessage?: string) => void;
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
    if (m.role === "user") {
      // Skip internal system-injected continuation messages (e.g. codex ack loop)
      if ((m.content ?? "").startsWith("[System:")) return;
      out.push({ id: nid(), role: "user", content: m.content ?? "", sessionIdx: i });
    } else if (m.role === "assistant") {
      const reasoning = m.reasoning?.trim();
      if (reasoning) {
        out.push({ id: nid(), role: "reasoning", text: reasoning });
      }
      if (m.content?.trim()) {
        out.push({ id: nid(), role: "assistant", content: m.content });
      }
    } else if (m.role === "tool") {
      const toolId = m.tool_call_id ?? "";
      out.push({
        id: nid(),
        role: "tool",
        toolId,
        name: m.tool_name ?? toolCallNames[toolId] ?? "tool",
        args: {},
        result: m.content ?? "",
        done: true,
      });
    }
  });
  return out;
}

// ── Memoized row components ───────────────────────────────────────────────────
// Defined at module scope so their identity is stable — React.memo bails out
// any row whose props haven't changed, preventing re-renders of the full
// message list on every streaming token.

// Highlight @file and /command tokens in plain text (used in user message bubbles)
const BUBBLE_TOKEN_RE = /(@\S+)|(^\/\S+)/gm;

function SparkAgentIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <img
      src="/icon_small-dark.png"
      alt=""
      aria-hidden="true"
      className={cn("block object-contain", className)}
      draggable={false}
    />
  );
}

function SparkAgentAvatar() {
  return (
    <div className="shrink-0 h-7 w-7 rounded-full flex items-center justify-center bg-success/20">
      <SparkAgentIcon />
    </div>
  );
}

function renderTokens(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let last = 0;
  BUBBLE_TOKEN_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = BUBBLE_TOKEN_RE.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    nodes.push(<span key={m.index} className="text-primary font-medium">{m[0]}</span>);
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

type UserMsg = Extract<ChatMessage, { role: "user" }>;
type AssistantMsg = Extract<ChatMessage, { role: "assistant" }>;
type ToolMsg = Extract<ChatMessage, { role: "tool" }>;
type ReasoningMsg = Extract<ChatMessage, { role: "reasoning" }>;
type ApprovalMsg = Extract<ChatMessage, { role: "approval" }>;
type NoteMsg = Extract<ChatMessage, { role: "note" }>;
type FeedbackFormMsg = Extract<ChatMessage, { role: "feedback_form" }>;

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
  return (
    <div className="flex gap-2 flex-row-reverse group/msg">
      <div className="shrink-0 h-7 w-7 rounded-full flex items-center justify-center text-xs bg-primary/20 text-primary">
        <User className="h-3.5 w-3.5" />
      </div>
      <div className="max-w-[85%] rounded-lg px-3 py-2 text-sm bg-primary/10 text-foreground relative">
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
    </div>
  );
});

const AssistantRow = memo(function AssistantRow({ msg }: { msg: AssistantMsg }) {
  return (
    <div className="flex gap-2">
      <SparkAgentAvatar />
      <div className="max-w-[85%] rounded-lg px-3 py-2 text-sm bg-secondary text-foreground min-w-0">
        {msg.content ? (
          <Markdown content={msg.content} />
        ) : (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" />
            <span className="text-xs">Thinking…</span>
          </span>
        )}
        {msg.streaming && msg.content ? (
          <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-success align-middle" />
        ) : null}
      </div>
    </div>
  );
});

const ToolRow = memo(function ToolRow({ msg, repeatCount }: { msg: ToolMsg; repeatCount: number }) {
  return (
    <div className="pl-9">
      <ToolCallBubble
        name={msg.name} args={msg.args} result={msg.result} done={msg.done}
        startedAt={msg.startedAt} endedAt={msg.endedAt}
        repeatCount={repeatCount > 0 ? repeatCount : undefined}
      />
    </div>
  );
});

const ReasoningRow = memo(function ReasoningRow({ msg, isActive }: { msg: ReasoningMsg; isActive?: boolean }) {
  return <div className="pl-9"><ReasoningBubble text={msg.text} isActive={isActive} /></div>;
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
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(sessionId);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusLabel, setStatusLabel] = useState<string | null>(null);
  const [approvalBusy, setApprovalBusy] = useState(false);
  const [editingUser, setEditingUser] = useState<{ sessionIdx: number; text: string } | null>(null);
  const [sessionStats, setSessionStats] = useState<SessionStats>({});
  const [forkInfo, setForkInfo] = useState<{
    parentSessionId: string | null;
    parentTitle: string | null;
    forkCount: number;
  } | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const activeSessionRef = useRef<string | null>(sessionId);
  const streamingRef = useRef(false);
  // Token batching: accumulate tokens and flush once per animation frame
  const tokenBufferRef = useRef("");
  const rafPendingRef = useRef<number | null>(null);
  // Scroll: only scroll once per rAF frame, instant during streaming
  const scrollRafRef = useRef<number | null>(null);

  activeSessionRef.current = activeSessionId;
  streamingRef.current = streaming;

  useEffect(() => {
    if (sessionId && sessionId === activeSessionRef.current && streamingRef.current) {
      return;
    }
    // Cancel any pending rAF flushes from the previous session
    if (rafPendingRef.current !== null) {
      cancelAnimationFrame(rafPendingRef.current);
      rafPendingRef.current = null;
      tokenBufferRef.current = "";
    }
    if (scrollRafRef.current !== null) {
      cancelAnimationFrame(scrollRafRef.current);
      scrollRafRef.current = null;
    }
    setActiveSessionId(sessionId);
    const optimistic: ChatMessage[] = initialMessage
      ? [{ id: nid(), role: "user", content: initialMessage }]
      : [];
    setChatMessages(optimistic);
    setError(null);
    setStatusLabel(null);
    setEditingUser(null);
    setSessionStats({});
    setForkInfo(null);
    if (sessionId) {
      api.getSessionForks(sessionId).then((info) => {
        setForkInfo({
          parentSessionId: info.parent_session_id,
          parentTitle: info.parent_title,
          forkCount: info.fork_count,
        });
      }).catch(() => {});
      setLoadingHistory(true);
      api
        .getSessionMessages(sessionId)
        .then((resp) => {
          // If the requested session was compressed, the backend returns
          // the leaf session_id. Re-pin our refs so streaming events and
          // turn_done re-fetches use the agent's actual current session.
          if (resp.session_id && resp.session_id !== activeSessionRef.current) {
            activeSessionRef.current = resp.session_id;
            setActiveSessionId(resp.session_id);
          }
          const mapped = sessionMessagesToChat(
            resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
          );
          setChatMessages((prev) => (mapped.length === 0 && prev.length > 0 ? prev : mapped));
        })
        .catch(() => setError("Failed to load conversation history."))
        .finally(() => setLoadingHistory(false));
    }
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to bottom at most once per frame; instant during streaming to avoid stacking animations
  const scheduleScroll = useCallback(() => {
    if (scrollRafRef.current !== null) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      messagesEndRef.current?.scrollIntoView({
        behavior: streamingRef.current ? "instant" : "smooth",
      });
    });
  }, []);

  useEffect(() => {
    scheduleScroll();
  }, [chatMessages, scheduleScroll]);

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
    const buffered = tokenBufferRef.current;
    tokenBufferRef.current = "";
    if (!buffered) return;
    setChatMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "assistant" && last.streaming) {
        next[next.length - 1] = { ...last, content: last.content + buffered };
      } else {
        next.push({ id: nid(), role: "assistant", content: buffered, streaming: true });
      }
      return next;
    });
  }, []);

  // Accumulate tokens and flush once per animation frame instead of on every token
  const appendToken = useCallback((token: string) => {
    tokenBufferRef.current += token;
    if (rafPendingRef.current === null) {
      rafPendingRef.current = requestAnimationFrame(flushTokenBuffer);
    }
  }, [flushTokenBuffer]);

  useEventBus((env) => {
    const sid = env.session_id ?? undefined;
    if (!sid || sid !== activeSessionRef.current) return;
    const data = env.data as Record<string, unknown>;

    switch (env.topic) {
      case "chat.token": {
        const t = data.t;
        if (typeof t === "string" && t) appendToken(t);
        break;
      }
      case "chat.tool_start": {
        if (rafPendingRef.current !== null) {
          cancelAnimationFrame(rafPendingRef.current);
          flushTokenBuffer();
        }
        finalizeAssistant();
        setChatMessages((prev) => [
          ...prev,
          {
            id: nid(),
            role: "tool",
            toolId: String(data.id ?? ""),
            name: String(data.name ?? "tool"),
            args: (data.args as Record<string, unknown>) ?? {},
            done: false,
            startedAt: typeof data.ts === "number" ? data.ts : undefined,
          },
        ]);
        setStatusLabel(`Tool: ${String(data.name ?? "")}`);
        break;
      }
      case "chat.tool_end": {
        const tid = String(data.id ?? "");
        setChatMessages((prev) => {
          const next = [...prev];
          for (let i = next.length - 1; i >= 0; i--) {
            const row = next[i];
            if (row.role === "tool" && row.toolId === tid) {
              next[i] = {
                ...row,
                result: String(data.result ?? ""),
                done: true,
                endedAt: typeof data.ts === "number" ? data.ts : undefined,
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
        if (text) {
          setChatMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last?.role === "reasoning") {
              next[next.length - 1] = { ...last, text: last.text ? `${last.text}${text}` : text };
              return next;
            }
            next.push({ id: nid(), role: "reasoning", text });
            return next;
          });
        }
        break;
      }
      case "chat.status": {
        const msg = String((data as { message?: string }).message ?? "");
        if (msg) setStatusLabel(msg);
        break;
      }
      case "chat.approval_requested": {
        if (rafPendingRef.current !== null) {
          cancelAnimationFrame(rafPendingRef.current);
          flushTokenBuffer();
        }
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
        const newId = String((data as { new_session_id?: string }).new_session_id ?? "");
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
      case "chat.interrupted": {
        if (rafPendingRef.current !== null) {
          cancelAnimationFrame(rafPendingRef.current);
          flushTokenBuffer();
        }
        finalizeAssistant();
        const msg = (data as { message?: string }).message;
        setChatMessages((prev) => [
          ...prev,
          { id: nid(), role: "note", text: msg ? `Interrupted: ${msg}` : "Interrupted." },
        ]);
        setStreaming(false);
        setStatusLabel(null);
        break;
      }
      case "chat.turn_done": {
        // Flush any remaining buffered tokens before finalizing
        if (rafPendingRef.current !== null) {
          cancelAnimationFrame(rafPendingRef.current);
          flushTokenBuffer();
        }
        finalizeAssistant();
        setStreaming(false);
        setStatusLabel(null);
        // Extract token/cost stats from the richer payload
        {
          const tokens = data.tokens as Record<string, number> | undefined;
          const cost = typeof data.cost_usd === "number" ? data.cost_usd : undefined;
          const model = typeof data.model === "string" ? data.model : undefined;
          setSessionStats((prev) => ({
            model: model ?? prev.model,
            inputTokens: (prev.inputTokens ?? 0) + (tokens?.input ?? 0),
            outputTokens: (prev.outputTokens ?? 0) + (tokens?.output ?? 0),
            cacheReadTokens: (prev.cacheReadTokens ?? 0) + (tokens?.cache_read ?? 0),
            costUsd: (prev.costUsd ?? 0) + (cost ?? 0),
            turnCount: (prev.turnCount ?? 0) + 1,
          }));
        }
        const cur = activeSessionRef.current;
        if (cur) {
          onSessionUpdated?.(cur);
          // Sync session indices for retry/fork; delay to avoid competing with the final render
          setTimeout(() => {
            void api
              .getSessionMessages(cur)
              .then((resp) => {
                const mapped = sessionMessagesToChat(
                  resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
                );
                setChatMessages((prev) => {
                  if (mapped.length === 0 && prev.length > 0) return prev;
                  // Preserve ephemeral feedback forms across the DB sync
                  const forms = prev.filter((m) => m.role === "feedback_form");
                  return forms.length > 0 ? [...mapped, ...forms] : mapped;
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

  const sendMessage = async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setError(null);
    setChatMessages((prev) => [...prev, { id: nid(), role: "user", content: text }]);

    // /feedback is handled entirely in the frontend — inject the form immediately,
    // send to backend only to prevent agent fallthrough (backend returns "").
    if (text.trim() === "/feedback") {
      setChatMessages((prev) => [...prev, { id: nid(), role: "feedback_form" as const }]);
    }

    setStreaming(true);
    setStatusLabel("Thinking…");

    try {
      let sid = activeSessionId;

      if (!sid) {
        const resp = await api.postConversation(text);
        sid = resp.session_id;
        activeSessionRef.current = sid;
        setActiveSessionId(sid);
        onSessionCreated?.(sid, text);
      } else {
        activeSessionRef.current = sid;
        const resp = await api.postConversationMessage(sid, text);
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
    const sid = activeSessionId;
    if (!sid) return;
    try {
      await api.interruptConversation(sid);
    } catch {
      /* ignore */
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
      setStatusLabel("Thinking…");
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
  }, []);

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

  const uploadFiles = useCallback(async (files: File[]) => {
    const res = workspaceSlug
      ? await api.uploadWorkspaceFiles(workspaceSlug, files, "files")
      : await api.uploadChatFiles(files);
    const refs = res.saved.map((f) => {
      const path = "path" in f ? f.path : `files/${f.filename}`;
      return `@${path}`;
    });
    if (!refs.length) return;
    setInput((prev) => {
      const prefix = prev.trimEnd();
      const addition = refs.join(" ");
      return prefix ? `${prefix}\n${addition} ` : `${addition} `;
    });
  }, [workspaceSlug]);

  // Stable handlers passed to memoized row components
  const handleEdit = useCallback((idx: number, text: string) => {
    setEditingUser({ sessionIdx: idx, text });
  }, []);
  const handleRetry = useCallback((idx: number) => { void doRetry(idx); }, [doRetry]);
  const handleFork = useCallback((idx: number) => { void doFork(idx); }, [doFork]);

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

  // Build match positions from messages
  const searchMatches = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return [];
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
    return results;
  }, [chatMessages, searchQuery]);

  // Scroll active match into view
  useEffect(() => {
    if (!searchMatches.length) return;
    const idx = searchMatches[searchMatchIdx % searchMatches.length];
    const el = messageListRef.current?.children[idx] as HTMLElement | undefined;
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [searchMatchIdx, searchMatches]);

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

  return (
    <div
      className={cn("flex min-h-0 w-full flex-1 flex-col bg-background relative", className)}
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
      <div className="flex items-center justify-between border-b border-border px-4 py-3 shrink-0 gap-2">
        {onBack && (
          <Button variant="ghost" size="icon" className="h-8 w-8 md:hidden" onClick={onBack}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
        )}
        <div className="flex flex-col gap-1 min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <StatusPill streaming={streaming} label={statusLabel} />
            {forkInfo?.parentSessionId && (
              <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground border border-border rounded px-1.5 py-0.5">
                <CornerUpLeft className="h-2.5 w-2.5" />
                Forked from {forkInfo.parentTitle ?? forkInfo.parentSessionId}
              </span>
            )}
            {forkInfo && forkInfo.forkCount > 0 && (
              <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground border border-border rounded px-1.5 py-0.5">
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
      </div>

      {/* Message search bar */}
      {searchOpen && (
        <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 bg-muted/30 shrink-0">
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

      <div className="flex-1 overflow-y-auto px-4 py-4">
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
          <div className="flex flex-col gap-3" ref={messageListRef}>
            {(() => {
              // Collapse consecutive same-name tool calls into one bubble with a repeat count.
              const collapsed: { msg: typeof chatMessages[number]; repeatCount: number }[] = [];
              for (const msg of chatMessages) {
                const prev = collapsed[collapsed.length - 1];
                if (
                  msg.role === "tool" &&
                  prev?.msg.role === "tool" &&
                  msg.name === (prev.msg as Extract<typeof msg, { role: "tool" }>).name
                ) {
                  collapsed[collapsed.length - 1] = { msg, repeatCount: prev.repeatCount + 1 };
                } else {
                  collapsed.push({ msg, repeatCount: 0 });
                }
              }
              return collapsed.map(({ msg, repeatCount }, idx) => {
                if (msg.role === "user") {
                  return (
                    <UserRow key={msg.id} msg={msg} hasSession={!!activeSessionId}
                      streaming={streaming} onEdit={handleEdit} onRetry={handleRetry}
                      onFork={handleFork} onCopy={copyText} />
                  );
                }
                if (msg.role === "assistant") {
                  if (!msg.content && !msg.streaming) return null;
                  return <AssistantRow key={msg.id} msg={msg} />;
                }
                if (msg.role === "tool") {
                  return <ToolRow key={msg.id} msg={msg} repeatCount={repeatCount} />;
                }
                if (msg.role === "reasoning") {
                  return <ReasoningRow key={msg.id} msg={msg} isActive={streaming && idx === collapsed.length - 1} />;
                }
                if (msg.role === "approval") {
                  return <ApprovalRow key={msg.id} msg={msg} disabled={approvalBusy} onChoice={submitApproval} />;
                }
                if (msg.role === "note") {
                  return <NoteRow key={msg.id} msg={msg} />;
                }
                if (msg.role === "feedback_form") {
                  return (
                    <FeedbackRow
                      key={msg.id}
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
                return null;
              });
            })()}
            {/* Typing indicator: shows immediately after send, before first token arrives */}
            {streaming && (() => {
              const last = chatMessages[chatMessages.length - 1];
              const isAlreadyStreamingAssistant =
                last?.role === "assistant" && (last.streaming || !last.content);
              if (isAlreadyStreamingAssistant) return null;
              return (
                <div className="flex gap-2">
                  <SparkAgentAvatar />
                  <div className="rounded-lg px-3 py-2.5 text-sm bg-secondary">
                    <span className="flex gap-[4px] items-center">
                      <span className="h-2 w-2 rounded-full bg-foreground/40 animate-bounce [animation-delay:0ms]" />
                      <span className="h-2 w-2 rounded-full bg-foreground/40 animate-bounce [animation-delay:150ms]" />
                      <span className="h-2 w-2 rounded-full bg-foreground/40 animate-bounce [animation-delay:300ms]" />
                    </span>
                  </div>
                </div>
              );
            })()}
          </div>
        )}
        {error && (
          <div className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2">
            <p className="text-xs text-destructive">{error}</p>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {editingUser && (
        <div className="border-t border-border px-4 py-2 bg-secondary/20 shrink-0 space-y-2">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Edit & retry</p>
          <textarea
            className="w-full rounded border border-input bg-background px-2 py-1.5 text-xs min-h-[72px]"
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

      <PromptBar
        input={input}
        setInput={setInput}
        streaming={streaming}
        onSend={() => void sendMessage()}
        onStop={() => void stop()}
        onUploadFiles={uploadFiles}
        disabled={!!editingUser}
        workspaceSlug={workspaceSlug}
      />
    </div>
  );
}
