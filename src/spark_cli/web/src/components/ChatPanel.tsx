import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  X,
  Send,
  Bot,
  User,
  Loader2,
  Square,
  GitFork,
  RotateCcw,
  Copy,
  Pencil,
} from "lucide-react";
import { api } from "@/lib/api";
import type { SessionMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/Markdown";
import { Button } from "@/components/ui/button";
import { useEventBus } from "@/hooks/useEventBus";
import { ToolCallBubble } from "@/components/chat/ToolCallBubble";
import { ReasoningBubble } from "@/components/chat/ReasoningBubble";
import { ApprovalPrompt } from "@/components/chat/ApprovalPrompt";
import { StatusPill } from "@/components/chat/StatusPill";

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
    }
  | { id: string; role: "reasoning"; text: string }
  | {
      id: string;
      role: "approval";
      approval: Record<string, unknown>;
      resolved?: boolean;
    }
  | { id: string; role: "note"; text: string };

interface ChatPanelProps {
  sessionId: string | null;
  onClose?: () => void;
  onBack?: () => void;
  onSessionCreated?: (id: string) => void;
  onSessionUpdated?: (id: string) => void;
  sessionTitle?: string | null;
  className?: string;
}

function sessionMessagesToChat(messages: SessionMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  messages.forEach((m, i) => {
    if (m.role === "user") {
      out.push({ id: nid(), role: "user", content: m.content ?? "", sessionIdx: i });
    } else if (m.role === "assistant") {
      out.push({ id: nid(), role: "assistant", content: m.content ?? "" });
    } else if (m.role === "tool") {
      out.push({
        id: nid(),
        role: "tool",
        toolId: m.tool_call_id ?? "",
        name: m.tool_name ?? "tool",
        args: {},
        result: m.content ?? "",
        done: true,
      });
    }
  });
  return out;
}

export function ChatPanel({
  sessionId,
  onClose,
  onBack,
  onSessionCreated,
  onSessionUpdated,
  sessionTitle,
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

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const activeSessionRef = useRef<string | null>(sessionId);

  activeSessionRef.current = activeSessionId;

  useEffect(() => {
    setActiveSessionId(sessionId);
    setChatMessages([]);
    setError(null);
    setStatusLabel(null);
    setEditingUser(null);
    if (sessionId) {
      setLoadingHistory(true);
      api
        .getSessionMessages(sessionId)
        .then((resp) => {
          const mapped = sessionMessagesToChat(
            resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
          );
          setChatMessages(mapped);
        })
        .catch(() => setError("Failed to load conversation history."))
        .finally(() => setLoadingHistory(false));
    }
  }, [sessionId]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

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

  const appendToken = useCallback((token: string) => {
    setChatMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "assistant" && last.streaming) {
        next[next.length - 1] = { ...last, content: last.content + token };
      } else {
        next.push({ id: nid(), role: "assistant", content: token, streaming: true });
      }
      return next;
    });
  }, []);

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
        if (text)
          setChatMessages((prev) => [...prev, { id: nid(), role: "reasoning", text }]);
        break;
      }
      case "chat.status": {
        const msg = String((data as { message?: string }).message ?? "");
        if (msg) setStatusLabel(msg);
        break;
      }
      case "chat.approval_requested": {
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
      case "chat.interrupted": {
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
        finalizeAssistant();
        setStreaming(false);
        setStatusLabel(null);
        const cur = activeSessionRef.current;
        if (cur) {
          onSessionUpdated?.(cur);
          void api
            .getSessionMessages(cur)
            .then((resp) =>
              setChatMessages(
                sessionMessagesToChat(
                  resp.messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool"),
                ),
              ),
            )
            .catch(() => {});
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
    setStreaming(true);
    setStatusLabel("Thinking…");

    try {
      let sid = activeSessionId;

      if (!sid) {
        const resp = await api.postConversation(text);
        sid = resp.session_id;
        activeSessionRef.current = sid;
        setActiveSessionId(sid);
        onSessionCreated?.(sid);
      } else {
        activeSessionRef.current = sid;
        const resp = await api.postConversationMessage(sid, text);
        if (resp.session_id && resp.session_id !== sid) {
          sid = resp.session_id;
          activeSessionRef.current = sid;
          setActiveSessionId(sid);
          onSessionCreated?.(sid);
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

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
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

  const doFork = async (fromSessionIdx?: number) => {
    const sid = activeSessionId;
    if (!sid) return;
    try {
      const r = await api.forkConversation(sid, fromSessionIdx);
      setActiveSessionId(r.session_id);
      onSessionCreated?.(r.session_id);
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
  };

  const doRetry = async (sessionIdx: number, edited?: string) => {
    const sid = activeSessionId;
    if (!sid || streaming) return;
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
  };

  const submitApproval = async (choice: "once" | "session" | "always" | "deny") => {
    const sid = activeSessionId;
    if (!sid) return;
    setApprovalBusy(true);
    try {
      await api.submitConversationApproval(sid, choice);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setApprovalBusy(false);
    }
  };

  const copyText = (t: string) => {
    void navigator.clipboard.writeText(t);
  };

  return (
    <div className={cn("flex min-h-0 w-full flex-1 flex-col bg-background", className)}>
      <div className="flex items-center justify-between border-b border-border px-4 py-3 shrink-0 gap-2">
        {onBack && (
          <Button variant="ghost" size="icon" className="h-8 w-8 md:hidden" onClick={onBack}>
            <ChevronLeft className="h-4 w-4" />
          </Button>
        )}
        <div className="flex flex-col gap-1 min-w-0 flex-1">
          <span className="text-sm font-semibold truncate">
            {activeSessionId ? sessionTitle || "Conversation" : "New thread"}
          </span>
          <div className="flex items-center gap-2 flex-wrap">
            <StatusPill streaming={streaming} label={statusLabel} />
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
          {streaming && activeSessionId && (
            <Button variant="destructive" size="sm" className="h-7 gap-1 text-xs" onClick={stop}>
              <Square className="h-3 w-3" />
              Stop
            </Button>
          )}
          {onClose && (
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {loadingHistory ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : chatMessages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
            <Bot className="h-10 w-10 mb-3 opacity-30" />
            <p className="text-sm">Start a conversation</p>
            <p className="text-xs mt-1 opacity-60">Type a message below</p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {chatMessages.map((msg) => {
              if (msg.role === "user") {
                return (
                  <div key={msg.id} className="flex gap-2 flex-row-reverse group/msg">
                    <div className="shrink-0 h-7 w-7 rounded-full flex items-center justify-center text-xs bg-primary/20 text-primary">
                      <User className="h-3.5 w-3.5" />
                    </div>
                    <div className="max-w-[85%] rounded-lg px-3 py-2 text-sm bg-primary/10 text-foreground relative">
                      <p className="whitespace-pre-wrap leading-relaxed">{msg.content}</p>
                      {activeSessionId && msg.sessionIdx != null && (
                        <div className="absolute -top-2 right-0 opacity-0 group-hover/msg:opacity-100 flex gap-1 transition-opacity">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            title="Edit & retry"
                            onClick={() =>
                              setEditingUser({ sessionIdx: msg.sessionIdx!, text: msg.content })
                            }
                          >
                            <Pencil className="h-3 w-3" />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            title="Retry"
                            disabled={streaming}
                            onClick={() => void doRetry(msg.sessionIdx!)}
                          >
                            <RotateCcw className="h-3 w-3" />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            title="Fork from here"
                            disabled={streaming}
                            onClick={() => void doFork(msg.sessionIdx)}
                          >
                            <GitFork className="h-3 w-3" />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            title="Copy"
                            onClick={() => copyText(msg.content)}
                          >
                            <Copy className="h-3 w-3" />
                          </Button>
                        </div>
                      )}
                    </div>
                  </div>
                );
              }
              if (msg.role === "assistant") {
                return (
                  <div key={msg.id} className="flex gap-2">
                    <div className="shrink-0 h-7 w-7 rounded-full flex items-center justify-center text-xs bg-success/20 text-success">
                      <Bot className="h-3.5 w-3.5" />
                    </div>
                    <div className="max-w-[85%] rounded-lg px-3 py-2 text-sm bg-secondary text-foreground min-w-0">
                      {msg.content ? (
                        <Markdown content={msg.content} />
                      ) : msg.streaming ? (
                        <span className="inline-flex items-center gap-1 text-muted-foreground">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          <span className="text-xs">Thinking…</span>
                        </span>
                      ) : null}
                      {msg.streaming && msg.content ? (
                        <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse bg-success align-middle" />
                      ) : null}
                    </div>
                  </div>
                );
              }
              if (msg.role === "tool") {
                return (
                  <div key={msg.id} className="pl-9">
                    <ToolCallBubble name={msg.name} args={msg.args} result={msg.result} done={msg.done} />
                  </div>
                );
              }
              if (msg.role === "reasoning") {
                return (
                  <div key={msg.id} className="pl-9">
                    <ReasoningBubble text={msg.text} />
                  </div>
                );
              }
              if (msg.role === "approval") {
                return (
                  <div key={msg.id} className="pl-2">
                    <ApprovalPrompt
                      command={String(msg.approval.command ?? "")}
                      description={String(msg.approval.description ?? "")}
                      disabled={approvalBusy || !!msg.resolved}
                      onChoice={(c) => void submitApproval(c)}
                    />
                  </div>
                );
              }
              if (msg.role === "note") {
                return (
                  <p key={msg.id} className="text-xs text-muted-foreground italic pl-2">
                    {msg.text}
                  </p>
                );
              }
              return null;
            })}
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

      <div className="border-t border-border px-4 py-3 shrink-0">
        <div className="flex gap-2 items-end">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={streaming}
            placeholder={streaming ? "Agent is responding…" : "Message… (Enter to send, Shift+Enter newline)"}
            rows={1}
            className="flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50 min-h-[40px] max-h-[160px] overflow-y-auto"
            style={{ height: "auto" }}
            onInput={(e) => {
              const el = e.currentTarget;
              el.style.height = "auto";
              el.style.height = Math.min(el.scrollHeight, 160) + "px";
            }}
          />
          <Button
            size="icon"
            className="h-10 w-10 shrink-0"
            disabled={!input.trim() || streaming}
            onClick={() => void sendMessage()}
          >
            {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
}
