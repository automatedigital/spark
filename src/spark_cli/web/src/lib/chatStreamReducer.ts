import type { ChatMessage } from "./chatTranscriptMerge";
import { currentTurnLiveAssistantIndex } from "./chatTranscriptMerge";
import { windowLiveStream, snapshotLiveStream } from "./liveStreamWindow";
import { appendBoundedText, boundText, REASONING_WINDOW_CHARS } from "./textWindow";

/**
 * Pure reduction contract for the live chat stream.
 *
 * This module deliberately has no React, timers, random IDs, network calls,
 * or side effects. The controller owns scheduling and effect execution while
 * this reducer remains the single event-topic reduction seam.
 */

export type ChatStreamTurnState =
  | "idle"
  | "starting"
  | "streaming"
  | "stalled"
  | "stopping"
  | "redirecting"
  | "awaiting-approval"
  | "awaiting-input"
  | "interrupted"
  | "failed"
  | "finalizing";

export type ChatStreamTopic =
  | "chat.token"
  | "chat.reasoning"
  | "chat.tool_start"
  | "chat.tool_end"
  | "chat.status"
  | "chat.subagent.created"
  | "chat.approval_requested"
  | "chat.approval_resolved"
  | "chat.input_requested"
  | "chat.requested_input"
  | "chat.input_resolved"
  | "chat.interrupted"
  | "chat.turn_done"
  | "chat.error"
  | "chat.failed"
  | "chat.session_migrated"
  | "chat.compaction"
  | "bus.reconnected"
  | "bus.gap"
  | "bus.stale"
  | "bus.wake";

export interface ChatStreamEvent {
  topic: string;
  session_id?: string | null;
  sequence?: number;
  data?: unknown;
}

export interface ChatStreamSnapshot {
  session_id?: string | null;
  resolved_session_id?: string | null;
  latest_session_id?: string | null;
  active_turn_session_id?: string | null;
  turn_active: boolean;
  state?: string | null;
  phase?: string | null;
  status?: string | null;
  reason?: string | null;
  interrupt_requested?: boolean;
  stream_text?: string | null;
  stream_revision?: number | null;
  stream_text_chars?: number | null;
  stream_text_start?: number | null;
  stream_text_mode?: string | null;
  stream_text_complete?: boolean;
}

export interface ChatStreamPendingInput {
  id?: string;
  prompt?: string;
  fields?: readonly unknown[];
  data: Readonly<Record<string, unknown>>;
}

export interface ChatStreamStats {
  model?: string;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheWriteTokens: number;
  costUsd: number;
  turnCount: number;
}

export interface ChatStreamState {
  activeSessionId: string | null;
  activeTurnSessionId: string | null;
  /** Aliases survive compressed-session migration and are used for guards. */
  sessionAliases: readonly string[];
  recoverySequence: number;
  messages: readonly ChatMessage[];
  turnState: ChatStreamTurnState;
  statusLabel: string | null;
  error: string | null;
  tokenBuffer: string;
  reasoningBuffer: string;
  reasoningBufferedChars: number;
  streamRevision: number;
  streamTextChars: number;
  pendingApproval: boolean;
  pendingInput: ChatStreamPendingInput | null;
  interrupted: boolean;
  finalized: boolean;
  failed: boolean;
  needsRecovery: boolean;
  recoveryReason: string | null;
  lastEventSequence: number | null;
  stats: ChatStreamStats;
  messageIdPrefix: string;
  nextMessageId: number;
}

type NewChatMessage = {
  [Role in ChatMessage["role"]]: Omit<Extract<ChatMessage, { role: Role }>, "id">
}[ChatMessage["role"]];

export type ChatStreamEffect =
  | { type: "flush-stream"; reason: FlushReason }
  | { type: "resync"; reason: "reconnect" | "gap" | "stale" | "wake" | "interrupted"; allowIdle: boolean }
  | { type: "load-history"; sessionId: string; reason: "turn-done" | "failure" | "snapshot-finalized" };

export type FlushReason = "manual" | "tool-start" | "approval" | "input" | "interrupt" | "turn-done" | "snapshot";

export type ChatStreamAction =
  | { type: "event"; event: ChatStreamEvent }
  | { type: "flush"; reason?: FlushReason }
  | { type: "finalize" }
  | { type: "sync-messages"; messages: readonly ChatMessage[] }
  | {
      type: "set-session";
      sessionId: string | null;
      recoverySequence?: number;
      aliases?: readonly string[];
      messages?: readonly ChatMessage[];
    }
  | { type: "reconnect-snapshot"; snapshot: ChatStreamSnapshot };

export interface ChatStreamTransition {
  state: ChatStreamState;
  effects: readonly ChatStreamEffect[];
  accepted: boolean;
}

const RECOVERY_TOPICS = new Set<ChatStreamTopic>([
  "bus.reconnected",
  "bus.gap",
  "bus.stale",
  "bus.wake",
]);

const CHAT_TOPICS = new Set<ChatStreamTopic>([
  "chat.token",
  "chat.reasoning",
  "chat.tool_start",
  "chat.tool_end",
  "chat.status",
  "chat.subagent.created",
  "chat.approval_requested",
  "chat.approval_resolved",
  "chat.input_requested",
  "chat.requested_input",
  "chat.input_resolved",
  "chat.interrupted",
  "chat.turn_done",
  "chat.error",
  "chat.failed",
  "chat.session_migrated",
  "chat.compaction",
]);

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === "object" && value !== null && !Array.isArray(value)
);

function dataOf(event: ChatStreamEvent): Record<string, unknown> {
  return isRecord(event.data) ? event.data : {};
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function boolValue(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function copyState(state: ChatStreamState, patch: Partial<ChatStreamState>): ChatStreamState {
  return { ...state, ...patch };
}

function addAlias(state: ChatStreamState, ...ids: Array<string | null | undefined>): ChatStreamState {
  const aliases = [...state.sessionAliases];
  for (const id of ids) {
    if (id && !aliases.includes(id)) aliases.push(id);
  }
  return aliases.length === state.sessionAliases.length
    ? state
    : copyState(state, { sessionAliases: aliases });
}

function allocateMessage(state: ChatStreamState, message: NewChatMessage): { state: ChatStreamState; message: ChatMessage } {
  const id = `${state.messageIdPrefix}${state.nextMessageId + 1}`;
  return {
    state: copyState(state, { nextMessageId: state.nextMessageId + 1 }),
    message: { ...message, id } as ChatMessage,
  };
}

function appendMessage(state: ChatStreamState, message: NewChatMessage): ChatStreamState {
  const allocated = allocateMessage(state, message);
  return copyState(allocated.state, { messages: [...allocated.state.messages, allocated.message] });
}

function currentAssistantIndex(messages: readonly ChatMessage[]): number {
  return currentTurnLiveAssistantIndex([...messages]);
}

function flushBuffers(state: ChatStreamState): ChatStreamState {
  let next = state;
  const tokenText = state.tokenBuffer;
  const reasoningText = state.reasoningBuffer;

  if (tokenText) {
    const messages = [...next.messages];
    const index = currentAssistantIndex(messages);
    if (index >= 0 && messages[index]?.role === "assistant") {
      const message = messages[index];
      const windowed = windowLiveStream({
        content: message.content,
        totalChars: message.liveTotalChars ?? message.content.length,
        fenceCount: message.liveFenceCount ?? 0,
      }, tokenText);
      messages[index] = {
        ...message,
        content: windowed.content,
        liveTotalChars: windowed.totalChars,
        liveOmittedChars: windowed.omittedChars,
        liveFenceCount: windowed.fenceCount,
        renderRevision: (message.renderRevision ?? 0) + 1,
        streaming: true,
      };
      next = copyState(next, {
        messages,
        streamTextChars: Math.max(next.streamTextChars, windowed.totalChars),
      });
    } else {
      const windowed = snapshotLiveStream(tokenText);
      const allocated = allocateMessage(next, {
        role: "assistant",
        content: windowed.content,
        streaming: true,
        liveTotalChars: windowed.totalChars,
        liveOmittedChars: windowed.omittedChars,
        liveFenceCount: windowed.fenceCount,
        renderRevision: 1,
      });
      next = copyState(allocated.state, {
        messages: [...allocated.state.messages, allocated.message],
        streamTextChars: Math.max(next.streamTextChars, windowed.totalChars),
      });
    }
  }

  if (reasoningText) {
    const messages = [...next.messages];
    const last = messages[messages.length - 1];
    if (last?.role === "reasoning") {
      const bounded = appendBoundedText({
        text: last.text,
        totalChars: last.totalChars ?? last.text.length,
        omittedChars: last.omittedChars ?? 0,
      }, reasoningText, REASONING_WINDOW_CHARS);
      const extraChars = Math.max(0, state.reasoningBufferedChars - reasoningText.length);
      bounded.totalChars += extraChars;
      bounded.omittedChars = Math.max(0, bounded.totalChars - bounded.text.length);
      messages[messages.length - 1] = { ...last, ...bounded };
      next = copyState(next, { messages });
    } else {
      const bounded = boundText(reasoningText, REASONING_WINDOW_CHARS, state.reasoningBufferedChars);
      const allocated = allocateMessage(next, {
        role: "reasoning",
        text: bounded.text,
        totalChars: bounded.totalChars,
        omittedChars: bounded.omittedChars,
      });
      next = copyState(allocated.state, {
        messages: [...allocated.state.messages, allocated.message],
      });
    }
  }

  return copyState(next, {
    tokenBuffer: "",
    reasoningBuffer: "",
    reasoningBufferedChars: 0,
  });
}

function finalizeAssistant(state: ChatStreamState): ChatStreamState {
  const index = [...state.messages].findLastIndex((message) => message.role === "assistant" && message.streaming);
  if (index < 0) return state;
  const messages = [...state.messages];
  const message = messages[index];
  if (message.role === "assistant") messages[index] = { ...message, streaming: false };
  return copyState(state, { messages });
}

function note(state: ChatStreamState, text: string): ChatStreamState {
  return appendMessage(state, { role: "note", text });
}

function withSequence(state: ChatStreamState, sequence: number | undefined): ChatStreamState {
  return sequence === undefined
    ? state
    : copyState(state, { lastEventSequence: Math.max(state.lastEventSequence ?? 0, sequence) });
}

function eventSessionId(event: ChatStreamEvent, data: Record<string, unknown>): string | undefined {
  return event.session_id ?? stringValue(data.session_id);
}

function isSessionAccepted(state: ChatStreamState, event: ChatStreamEvent, data: Record<string, unknown>): boolean {
  if (RECOVERY_TOPICS.has(event.topic as ChatStreamTopic)) return Boolean(state.activeSessionId);
  const id = eventSessionId(event, data);
  if (!state.activeSessionId || !id) return false;
  if (state.sessionAliases.includes(id)) return true;
  if (event.topic === "chat.session_migrated") {
    return [data.old_session_id, data.new_session_id]
      .some((value) => typeof value === "string" && state.sessionAliases.includes(value));
  }
  return false;
}

function markStreaming(state: ChatStreamState): ChatStreamState {
  if (state.turnState === "stopping" || state.turnState === "redirecting") return state;
  return copyState(state, { turnState: "streaming", finalized: false, failed: false });
}

function statsForTurn(state: ChatStreamState, data: Record<string, unknown>): ChatStreamState {
  const tokens = isRecord(data.tokens) ? data.tokens : {};
  const inputTokens = numberValue(tokens.input) ?? 0;
  const outputTokens = numberValue(tokens.output) ?? 0;
  const cacheReadTokens = numberValue(tokens.cache_read) ?? 0;
  const cacheWriteTokens = numberValue(tokens.cache_write) ?? 0;
  const costUsd = numberValue(data.cost_usd) ?? 0;
  const model = stringValue(data.model);
  return copyState(state, {
    stats: {
      model: model ?? state.stats.model,
      inputTokens: state.stats.inputTokens + inputTokens,
      outputTokens: state.stats.outputTokens + outputTokens,
      cacheReadTokens: state.stats.cacheReadTokens + cacheReadTokens,
      cacheWriteTokens: state.stats.cacheWriteTokens + cacheWriteTokens,
      costUsd: state.stats.costUsd + costUsd,
      turnCount: state.stats.turnCount + 1,
    },
  });
}

function attachUsage(state: ChatStreamState, data: Record<string, unknown>): ChatStreamState {
  const tokens = isRecord(data.tokens) ? data.tokens : {};
  const totalTokens = (numberValue(tokens.input) ?? 0) + (numberValue(tokens.output) ?? 0);
  const costUsd = numberValue(data.cost_usd);
  if (totalTokens <= 0 && costUsd === undefined) return state;
  const messages = [...state.messages];
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "assistant") {
      messages[index] = { ...message, usage: { totalTokens, costUsd } };
      return copyState(state, { messages });
    }
  }
  return state;
}

function flushAndFinalize(state: ChatStreamState): ChatStreamState {
  return finalizeAssistant(flushBuffers(state));
}

function snapshotTurnState(snapshot: ChatStreamSnapshot): ChatStreamTurnState {
  if (snapshot.interrupt_requested || snapshot.state === "stopping") return "stopping";
  if (snapshot.state === "redirecting" || snapshot.phase === "redirecting") return "redirecting";
  if (snapshot.state === "stalled") return "stalled";
  if (snapshot.phase === "starting") return "starting";
  return "streaming";
}

function applySnapshotText(state: ChatStreamState, snapshot: ChatStreamSnapshot): ChatStreamState {
  const text = snapshot.stream_text ?? "";
  if (!text) return state;
  const revision = numberValue(snapshot.stream_revision);
  const start = numberValue(snapshot.stream_text_start);
  const reportedChars = numberValue(snapshot.stream_text_chars);
  const isDelta = start !== undefined && start > 0;
  const nextTotalChars = reportedChars ?? (isDelta ? start + text.length : text.length);

  if (!isDelta) {
    if (revision !== undefined && revision > 0 && revision < state.streamRevision) return state;
    if (revision !== undefined && revision === state.streamRevision && text.length <= state.streamTextChars) return state;
    if (revision === undefined && text.length <= state.streamTextChars) return state;
  }

  const messages = [...state.messages];
  const index = currentAssistantIndex(messages);
  const canAppend = isDelta && state.streamTextChars === start && index >= 0;
  const windowed = canAppend && messages[index]?.role === "assistant"
    ? windowLiveStream({
        content: messages[index].content,
        totalChars: messages[index].liveTotalChars ?? messages[index].content.length,
        fenceCount: messages[index].liveFenceCount ?? 0,
      }, text, nextTotalChars)
    : snapshotLiveStream(text, nextTotalChars);
  const nextMessage = {
    ...(index >= 0 && messages[index]?.role === "assistant" ? messages[index] : {}),
    role: "assistant",
    content: windowed.content,
    streaming: true,
    liveTotalChars: windowed.totalChars,
    liveOmittedChars: windowed.omittedChars,
    liveFenceCount: windowed.fenceCount,
    renderRevision: revision ?? ((index >= 0 && messages[index]?.role === "assistant" ? messages[index].renderRevision : 0) ?? 0) + 1,
  } as NewChatMessage;
  if (index >= 0 && messages[index]?.role === "assistant") {
    messages[index] = { ...messages[index], ...nextMessage } as ChatMessage;
  } else {
    const allocated = allocateMessage(state, nextMessage);
    messages.push(allocated.message);
    return copyState(allocated.state, {
      messages,
      streamRevision: Math.max(state.streamRevision, revision ?? 0),
      streamTextChars: Math.max(state.streamTextChars, nextTotalChars),
    });
  }
  return copyState(state, {
    messages,
    streamRevision: Math.max(state.streamRevision, revision ?? 0),
    streamTextChars: Math.max(state.streamTextChars, nextTotalChars),
  });
}

function reduceSnapshot(state: ChatStreamState, snapshot: ChatStreamSnapshot): ChatStreamTransition {
  const ids = [snapshot.session_id, snapshot.resolved_session_id, snapshot.latest_session_id, snapshot.active_turn_session_id]
    .filter((id): id is string => Boolean(id));
  if (!state.activeSessionId || !ids.some((id) => state.sessionAliases.includes(id))) {
    return { state, effects: [], accepted: false };
  }

  let next = addAlias(state, ...ids);
  if (snapshot.turn_active) {
    next = applySnapshotText(next, snapshot);
    next = copyState(next, {
      activeTurnSessionId: snapshot.active_turn_session_id ?? next.activeTurnSessionId ?? next.activeSessionId,
      turnState: snapshotTurnState(snapshot),
      statusLabel: snapshot.status ?? next.statusLabel,
      needsRecovery: false,
      recoveryReason: null,
      finalized: false,
    });
    return { state: next, effects: [], accepted: true };
  }

  next = flushAndFinalize(next);
  next = copyState(next, {
    activeTurnSessionId: null,
    turnState: "finalizing",
    statusLabel: "Finalizing from saved history…",
    needsRecovery: false,
    recoveryReason: null,
  });
  const sessionId = snapshot.latest_session_id ?? snapshot.resolved_session_id ?? next.activeSessionId;
  const effects = sessionId
    ? [{ type: "load-history", sessionId, reason: "snapshot-finalized" } satisfies ChatStreamEffect]
    : [];
  return { state: next, effects, accepted: true };
}

function reduceEvent(state: ChatStreamState, event: ChatStreamEvent): ChatStreamTransition {
  const topic = event.topic as ChatStreamTopic;
  if (!RECOVERY_TOPICS.has(topic) && !CHAT_TOPICS.has(topic)) return { state, effects: [], accepted: false };
  if (event.sequence !== undefined && state.lastEventSequence !== null && event.sequence <= state.lastEventSequence) {
    return { state, effects: [], accepted: false };
  }
  const data = dataOf(event);
  if (!isSessionAccepted(state, event, data)) return { state, effects: [], accepted: false };

  let next = withSequence(state, event.sequence);
  const effects: ChatStreamEffect[] = [];

  if (RECOVERY_TOPICS.has(topic)) {
    const reason = topic === "bus.reconnected" ? "reconnect" : topic === "bus.gap" ? "gap" : topic === "bus.stale" ? "stale" : "wake";
    next = copyState(next, { needsRecovery: true, recoveryReason: reason });
    effects.push({ type: "resync", reason, allowIdle: true });
    return { state: next, effects, accepted: true };
  }

  switch (topic) {
    case "chat.token": {
      const token = stringValue(data.t) ?? "";
      if (!token) return { state: next, effects: [], accepted: true };
      next = copyState(markStreaming(next), { tokenBuffer: `${next.tokenBuffer}${token}` });
      break;
    }
    case "chat.reasoning": {
      const text = stringValue(data.text) ?? "";
      if (!text) return { state: next, effects: [], accepted: true };
      next = markStreaming(next);
      next = copyState(next, {
        reasoningBuffer: `${next.reasoningBuffer}${text}`.slice(-REASONING_WINDOW_CHARS),
        reasoningBufferedChars: next.reasoningBufferedChars + text.length,
      });
      break;
    }
    case "chat.tool_start": {
      next = flushAndFinalize(next);
      const allocated = allocateMessage(next, {
        role: "tool",
        toolId: String(data.id ?? ""),
        name: String(data.name ?? "tool"),
        args: isRecord(data.args) ? data.args : {},
        done: false,
        startedAt: numberValue(data.started_at) ?? numberValue(data.ts),
      });
      next = copyState(allocated.state, {
        messages: [...allocated.state.messages, allocated.message],
        turnState: "streaming",
        statusLabel: `Tool: ${String(data.name ?? "")}`,
        finalized: false,
      });
      effects.push({ type: "flush-stream", reason: "tool-start" });
      break;
    }
    case "chat.tool_end": {
      const toolId = String(data.id ?? "");
      const messages = [...next.messages];
      for (let index = messages.length - 1; index >= 0; index -= 1) {
        const message = messages[index];
        if (message.role === "tool" && message.toolId === toolId) {
          messages[index] = {
            ...message,
            result: String(data.result_preview ?? data.result ?? ""),
            resultTruncated: Boolean(data.result_truncated ?? data.truncated) || undefined,
            done: true,
            endedAt: numberValue(data.ended_at) ?? numberValue(data.ts),
            durationSeconds: numberValue(data.duration_seconds),
          };
          break;
        }
      }
      next = copyState(markStreaming(next), { messages });
      break;
    }
    case "chat.status":
      next = copyState(next, { statusLabel: stringValue(data.message) ?? next.statusLabel });
      break;
    case "chat.subagent.created": {
      // Child runs are rendered by the side panel. Do not add a normal feed row.
      break;
    }
    case "chat.approval_requested": {
      next = flushAndFinalize(next);
      const approval = isRecord(data.approval) ? data.approval : data;
      next = appendMessage(next, { role: "approval", approval });
      next = copyState(next, {
        pendingApproval: true,
        turnState: "awaiting-approval",
        statusLabel: "Waiting for approval…",
      });
      effects.push({ type: "flush-stream", reason: "approval" });
      break;
    }
    case "chat.approval_resolved": {
      const messages = next.messages.map((message) => (
        message.role === "approval" && !message.resolved ? { ...message, resolved: true } : message
      ));
      next = copyState(next, {
        messages,
        pendingApproval: false,
        turnState: next.turnState === "awaiting-approval" ? "streaming" : next.turnState,
        statusLabel: null,
      });
      break;
    }
    case "chat.input_requested":
    case "chat.requested_input": {
      next = flushAndFinalize(next);
      const input = isRecord(data.input) ? data.input : data;
      next = copyState(next, {
        pendingInput: {
          id: stringValue(input.id),
          prompt: stringValue(input.prompt) ?? stringValue(input.message),
          fields: Array.isArray(input.fields) ? input.fields : undefined,
          data: input,
        },
        turnState: "awaiting-input",
        statusLabel: stringValue(input.prompt) ?? stringValue(input.message) ?? "Waiting for input…",
      });
      effects.push({ type: "flush-stream", reason: "input" });
      break;
    }
    case "chat.input_resolved":
      next = copyState(next, {
        pendingInput: null,
        turnState: next.turnState === "awaiting-input" ? "streaming" : next.turnState,
        statusLabel: null,
      });
      break;
    case "chat.session_migrated": {
      const oldId = stringValue(data.old_session_id);
      const newId = stringValue(data.new_session_id);
      next = addAlias(next, oldId, newId);
      if (newId) next = copyState(next, { activeSessionId: newId, activeTurnSessionId: newId });
      next = markStreaming(next);
      next = note(next, "Earlier conversation was summarized to free context space — the assistant may not recall fine-grained details from before this point.");
      break;
    }
    case "chat.compaction":
      if (data.status === "failed") {
        next = note(next, stringValue(data.message) ?? "Context compression failed. The transcript was preserved, and you can retry this message.");
        next = copyState(next, { statusLabel: null });
      }
      break;
    case "chat.interrupted": {
      next = flushAndFinalize(next);
      const redirecting = data.phase === "redirecting";
      next = note(next, stringValue(data.message) ? `Interrupted: ${String(data.message)}` : "Interrupted.");
      next = copyState(next, {
        turnState: redirecting ? "redirecting" : "stopping",
        statusLabel: redirecting ? "Redirecting…" : "Stopping…",
        interrupted: true,
      });
      effects.push({ type: "flush-stream", reason: "interrupt" });
      effects.push({ type: "resync", reason: "interrupted", allowIdle: false });
      break;
    }
    case "chat.error":
    case "chat.failed": {
      next = flushAndFinalize(next);
      const message = stringValue(data.message) ?? stringValue(data.error) ?? "The turn failed. You can retry this message.";
      next = note(next, message);
      next = copyState(next, {
        turnState: "failed",
        statusLabel: null,
        error: message,
        failed: true,
        finalized: true,
        activeTurnSessionId: null,
      });
      const sessionId = eventSessionId(event, data) ?? next.activeSessionId;
      if (sessionId) effects.push({ type: "load-history", sessionId, reason: "failure" });
      effects.push({ type: "flush-stream", reason: "turn-done" });
      break;
    }
    case "chat.turn_done": {
      next = flushAndFinalize(next);
      const interrupted = boolValue(data.interrupted) ?? false;
      const finalAssistantPresent = boolValue(data.final_assistant_present)
        ?? next.messages.some((message) => message.role === "assistant" && message.content.trim().length > 0);
      const backendErrorClass = stringValue(data.backend_error_class);
      next = attachUsage(next, data);
      next = statsForTurn(next, data);
      if (!interrupted && (!finalAssistantPresent || backendErrorClass)) {
        next = note(next, backendErrorClass
          ? `Turn ended with a backend error (${backendErrorClass}). You can retry this message.`
          : "Turn ended without a saved assistant response. You can retry this message.");
      }
      next = copyState(next, {
        activeTurnSessionId: null,
        turnState: "idle",
        statusLabel: null,
        finalized: true,
        interrupted,
        failed: Boolean(backendErrorClass),
        error: backendErrorClass ?? next.error,
        needsRecovery: false,
        recoveryReason: null,
      });
      const sessionId = eventSessionId(event, data) ?? next.activeSessionId;
      if (sessionId) effects.push({ type: "load-history", sessionId, reason: "turn-done" });
      effects.push({ type: "flush-stream", reason: "turn-done" });
      break;
    }
    default:
      return { state: next, effects: [], accepted: true };
  }

  return { state: next, effects, accepted: true };
}

export function createChatStreamState(input: {
  sessionId?: string | null;
  aliases?: readonly string[];
  recoverySequence?: number;
  messages?: readonly ChatMessage[];
  messageIdPrefix?: string;
} = {}): ChatStreamState {
  const sessionId = input.sessionId ?? null;
  return {
    activeSessionId: sessionId,
    activeTurnSessionId: null,
    sessionAliases: sessionId ? [...new Set([sessionId, ...(input.aliases ?? [])])] : [],
    recoverySequence: input.recoverySequence ?? 0,
    messages: [...(input.messages ?? [])],
    turnState: "idle",
    statusLabel: null,
    error: null,
    tokenBuffer: "",
    reasoningBuffer: "",
    reasoningBufferedChars: 0,
    streamRevision: 0,
    streamTextChars: 0,
    pendingApproval: false,
    pendingInput: null,
    interrupted: false,
    finalized: false,
    failed: false,
    needsRecovery: false,
    recoveryReason: null,
    lastEventSequence: null,
    stats: {
      inputTokens: 0,
      outputTokens: 0,
      cacheReadTokens: 0,
      cacheWriteTokens: 0,
      costUsd: 0,
      turnCount: 0,
    },
    messageIdPrefix: input.messageIdPrefix ?? "stream:",
    nextMessageId: 0,
  };
}

export function reduceChatStream(state: ChatStreamState, action: ChatStreamAction): ChatStreamTransition {
  switch (action.type) {
    case "event":
      return reduceEvent(state, action.event);
    case "flush": {
      return {
        state: flushBuffers(state),
        effects: [],
        accepted: true,
      };
    }
    case "finalize":
      return { state: flushAndFinalize(state), effects: [], accepted: true };
    case "sync-messages":
      return { state: copyState(state, { messages: [...action.messages] }), effects: [], accepted: true };
    case "set-session": {
      const sessionId = action.sessionId;
      const aliases = sessionId
        ? [...new Set([sessionId, ...(action.aliases ?? [])])]
        : [];
      return {
        state: createChatStreamState({
          sessionId,
          aliases,
          recoverySequence: action.recoverySequence ?? state.recoverySequence + 1,
          messages: action.messages,
          messageIdPrefix: state.messageIdPrefix,
        }),
        effects: [],
        accepted: true,
      };
    }
    case "reconnect-snapshot":
      return reduceSnapshot(state, action.snapshot);
  }
}

/** Conventional state-only adapter for callers that do not need effects yet. */
export function reduceChatStreamState(state: ChatStreamState, action: ChatStreamAction): ChatStreamState {
  return reduceChatStream(state, action).state;
}
