import type { ContextItem } from "./context";
import type { ChatMessage } from "./chatTranscriptMerge";
import {
  nextChatTurnState,
  type ChatTurnEvent,
  type ChatTurnState,
} from "./chatTurnState";

export const COMPOSER_LOADING_STATUS = "Loading LLM response";
export const COMPOSER_REDIRECTING_STATUS = "Redirecting…";
export const COMPOSER_STOPPING_STATUS = "Stopping…";

export type ComposerAction = "send" | "redirect" | "stop" | "retry" | "edit" | "fork";

export type ComposerGuardReason =
  | "empty-message"
  | "no-session"
  | "no-active-turn"
  | "interrupt-in-flight"
  | "turn-in-progress"
  | "invalid-message-index"
  | "message-not-found"
  | "unknown-action";

export interface ChatComposerState {
  sessionId: string | null;
  activeTurnSessionId: string | null;
  turnState: ChatTurnState;
  statusLabel: string | null;
  transcript: readonly ChatMessage[];
  contextItems: readonly ContextItem[];
}

export interface ComposerStateInput {
  sessionId?: string | null;
  activeTurnSessionId?: string | null;
  turnState?: ChatTurnState;
  statusLabel?: string | null;
  transcript?: readonly ChatMessage[];
  contextItems?: readonly ContextItem[];
}

export function createComposerState(input: ComposerStateInput = {}): ChatComposerState {
  return {
    sessionId: input.sessionId ?? null,
    activeTurnSessionId: input.activeTurnSessionId ?? null,
    turnState: input.turnState ?? "idle",
    statusLabel: input.statusLabel ?? null,
    transcript: [...(input.transcript ?? [])],
    contextItems: [...(input.contextItems ?? [])],
  };
}

export interface TargetSession {
  kind: "new" | "existing";
  sessionId: string | null;
  workspaceSlug: string | null;
}

export interface TargetSessionInput {
  sessionId?: string | null;
  activeSessionId?: string | null;
  workspaceSlug?: string | null;
}

function nonEmpty(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

/** Resolve a send target without reading React refs or calling the API. */
export function resolveTargetSession(input: TargetSessionInput): TargetSession {
  const sessionId = nonEmpty(input.activeSessionId) ?? nonEmpty(input.sessionId);
  return {
    kind: sessionId ? "existing" : "new",
    sessionId,
    workspaceSlug: sessionId ? null : nonEmpty(input.workspaceSlug),
  };
}

/** Resolve the session that owns a running turn, including migrated aliases. */
export function resolveTurnSession(state: Pick<ChatComposerState, "sessionId" | "activeTurnSessionId">): string | null {
  return nonEmpty(state.activeTurnSessionId) ?? nonEmpty(state.sessionId);
}

export function resolveResponseSession(
  state: ChatComposerState,
  responseSessionId: string | null | undefined,
): ChatComposerState {
  const sessionId = nonEmpty(responseSessionId);
  return sessionId ? { ...state, sessionId } : state;
}

export interface OptimisticUserRowInput {
  id: string;
  text: string;
  contextItems?: readonly ContextItem[];
  redirect?: boolean;
  sessionIdx?: number;
}

/** Build the exact user row that the UI may append before transport completes. */
export function optimisticUserRow(
  input: OptimisticUserRowInput,
): Extract<ChatMessage, { role: "user" }> {
  const text = input.text.trim();
  const contextItems = input.contextItems && input.contextItems.length > 0
    ? [...input.contextItems]
    : undefined;
  return {
    id: input.id,
    role: "user",
    content: text,
    ...(contextItems ? { contextItems } : {}),
    ...(input.redirect ? { redirect: true } : {}),
    ...(input.sessionIdx !== undefined ? { sessionIdx: input.sessionIdx } : {}),
  };
}

/** One-turn context is consumed by a successful or optimistic idle send. */
export function retainedContextItems(items: readonly ContextItem[]): ContextItem[] {
  return items.filter((item) => item.scope === "pinned").map((item) => ({ ...item }));
}

export type ComposerEffect =
  | {
      type: "start-conversation";
      message: string;
      contextItems: ContextItem[];
    }
  | {
      type: "start-workspace-conversation";
      workspaceSlug: string;
      message: string;
      contextItems: ContextItem[];
    }
  | {
      type: "post-conversation-message";
      sessionId: string;
      message: string;
      contextItems: ContextItem[];
    }
  | {
      type: "interrupt-conversation";
      sessionId: string;
      message?: string;
    }
  | {
      type: "retry-conversation";
      sessionId: string;
      messageIndex: number;
      message?: string;
    }
  | {
      type: "fork-conversation";
      sessionId: string;
      fromMessageIndex: number;
    };

export interface TurnTransitionIntent {
  type: "turn-transition";
  event: ChatTurnEvent;
  from: ChatTurnState;
  to: ChatTurnState;
  statusLabel: string | null;
}

export interface UserRowIntent {
  type: "append-user-row";
  row: ChatMessage;
}

export interface ContextRetentionIntent {
  type: "retain-context";
  before: ContextItem[];
  after: ContextItem[];
}

export interface EditIntent {
  type: "open-edit";
  messageIndex: number;
  messageId: string;
  text: string;
}

export type ComposerIntent = TurnTransitionIntent | UserRowIntent | ContextRetentionIntent | EditIntent;

export interface RejectedComposerPlan {
  accepted: false;
  action: ComposerAction;
  reason: ComposerGuardReason;
  effects: readonly [];
  intents: readonly [];
}

export interface AcceptedComposerPlan {
  accepted: true;
  action: ComposerAction;
  effects: readonly ComposerEffect[];
  intents: readonly ComposerIntent[];
  optimisticState: ChatComposerState;
  successState: ChatComposerState;
  rollbackState: ChatComposerState;
  target?: TargetSession;
}

export type ComposerPlan = RejectedComposerPlan | AcceptedComposerPlan;

function rejected(action: ComposerAction, reason: ComposerGuardReason): RejectedComposerPlan {
  return { accepted: false, action, reason, effects: [], intents: [] };
}

function transitionIntent(
  state: ChatComposerState,
  event: ChatTurnEvent,
  statusLabel: string | null,
): TurnTransitionIntent {
  return {
    type: "turn-transition",
    event,
    from: state.turnState,
    to: nextChatTurnState(state.turnState, event),
    statusLabel,
  };
}

function applyTransition(state: ChatComposerState, intent: TurnTransitionIntent): ChatComposerState {
  return {
    ...state,
    turnState: intent.to,
    statusLabel: intent.statusLabel,
  };
}

function activeInterruptInFlight(state: ChatComposerState): boolean {
  return state.turnState === "stopping" || state.turnState === "redirecting";
}

function hasUsableMessageIndex(value: number): boolean {
  return Number.isInteger(value) && value >= 0;
}

function findUserMessage(
  state: ChatComposerState,
  messageIndex: number,
): Extract<ChatMessage, { role: "user" }> | undefined {
  return state.transcript.find((message): message is Extract<ChatMessage, { role: "user" }> => (
    message.role === "user" && message.sessionIdx === messageIndex
  ));
}

function acceptedPlan(
  action: ComposerAction,
  state: ChatComposerState,
  nextState: ChatComposerState,
  effects: readonly ComposerEffect[],
  intents: readonly ComposerIntent[],
  target?: TargetSession,
  successState = nextState,
): AcceptedComposerPlan {
  return {
    accepted: true,
    action,
    effects,
    intents,
    optimisticState: nextState,
    successState,
    rollbackState: state,
    ...(target ? { target } : {}),
  };
}

export interface SendRequest {
  messageId: string;
  text: string;
  workspaceSlug?: string | null;
}

function planRedirect(state: ChatComposerState, request: SendRequest): ComposerPlan {
  const sessionId = resolveTurnSession(state);
  if (!sessionId) return rejected("redirect", "no-session");
  if (activeInterruptInFlight(state)) return rejected("redirect", "interrupt-in-flight");

  const row = optimisticUserRow({ id: request.messageId, text: request.text, redirect: true });
  const transition = transitionIntent(
    state,
    { type: "interrupt_requested", redirect: true },
    COMPOSER_REDIRECTING_STATUS,
  );
  const nextState = applyTransition(state, transition);
  nextState.transcript = [...state.transcript, row];
  return acceptedPlan(
    "redirect",
    state,
    nextState,
    [{ type: "interrupt-conversation", sessionId, message: row.content }],
    [transition, { type: "append-user-row", row }],
  );
}

/** Plan an idle send, or the redirect that an in-flight send becomes. */
export function planSend(state: ChatComposerState, request: SendRequest): ComposerPlan {
  const text = request.text.trim();
  if (!text) return rejected("send", "empty-message");
  if (state.turnState !== "idle") return planRedirect(state, { ...request, text });

  const target = resolveTargetSession({
    activeSessionId: state.sessionId,
    workspaceSlug: request.workspaceSlug,
  });
  const contextItems = state.contextItems.map((item) => ({ ...item }));
  const retained = retainedContextItems(contextItems);
  const row = optimisticUserRow({ id: request.messageId, text, contextItems });
  const transition = transitionIntent(state, { type: "submit" }, COMPOSER_LOADING_STATUS);
  const nextState = applyTransition(state, transition);
  nextState.transcript = [...state.transcript, row];
  nextState.contextItems = retained;

  let effect: ComposerEffect;
  if (target.kind === "existing") {
    effect = {
      type: "post-conversation-message",
      sessionId: target.sessionId!,
      message: text,
      contextItems,
    };
  } else if (target.workspaceSlug) {
    effect = {
      type: "start-workspace-conversation",
      workspaceSlug: target.workspaceSlug,
      message: text,
      contextItems,
    };
  } else {
    effect = { type: "start-conversation", message: text, contextItems };
  }

  return acceptedPlan(
    "send",
    state,
    nextState,
    [effect],
    [
      transition,
      { type: "append-user-row", row },
      { type: "retain-context", before: contextItems, after: retained },
    ],
    target,
  );
}

export function planRedirectAction(state: ChatComposerState, request: SendRequest): ComposerPlan {
  const text = request.text.trim();
  if (!text) return rejected("redirect", "empty-message");
  if (state.turnState === "idle") return rejected("redirect", "no-active-turn");
  return planRedirect(state, { ...request, text });
}

export function planStop(state: ChatComposerState): ComposerPlan {
  const sessionId = resolveTurnSession(state);
  if (!sessionId) return rejected("stop", "no-session");
  if (state.turnState === "idle") return rejected("stop", "no-active-turn");
  if (activeInterruptInFlight(state)) return rejected("stop", "interrupt-in-flight");

  const transition = transitionIntent(state, { type: "interrupt_requested" }, COMPOSER_STOPPING_STATUS);
  const nextState = applyTransition(state, transition);
  return acceptedPlan(
    "stop",
    state,
    nextState,
    [{ type: "interrupt-conversation", sessionId }],
    [transition],
  );
}

export interface RetryRequest {
  messageIndex: number;
  editedText?: string;
}

/**
 * Match ChatPanel's post-success local retry cleanup: remove only trailing
 * work rows, then edit the targeted user row if it is the current tail turn.
 */
export function truncateTranscriptForRetry(
  transcript: readonly ChatMessage[],
  messageIndex: number,
  editedText?: string,
): ChatMessage[] {
  const next = [...transcript];
  while (next.length > 0) {
    const last = next[next.length - 1];
    if (
      last.role === "assistant" ||
      last.role === "tool" ||
      last.role === "reasoning" ||
      last.role === "note"
    ) {
      next.pop();
      continue;
    }
    if (last.role === "user" && last.sessionIdx === messageIndex && editedText !== undefined) {
      next[next.length - 1] = { ...last, content: editedText };
    }
    break;
  }
  return next;
}

export function planRetry(state: ChatComposerState, request: RetryRequest): ComposerPlan {
  if (!resolveTurnSession(state)) return rejected("retry", "no-session");
  if (state.turnState !== "idle") return rejected("retry", "turn-in-progress");
  if (!hasUsableMessageIndex(request.messageIndex)) return rejected("retry", "invalid-message-index");
  const message = findUserMessage(state, request.messageIndex);
  if (!message) return rejected("retry", "message-not-found");

  const sessionId = resolveTurnSession(state)!;
  const successTranscript = truncateTranscriptForRetry(
    state.transcript,
    request.messageIndex,
    request.editedText,
  );
  const nextState = {
    ...state,
    transcript: successTranscript,
    turnState: "streaming" as const,
    statusLabel: COMPOSER_LOADING_STATUS,
  };
  const effect: ComposerEffect = {
    type: "retry-conversation",
    sessionId,
    messageIndex: request.messageIndex,
    ...(request.editedText !== undefined ? { message: request.editedText } : {}),
  };
  return acceptedPlan(
    "retry",
    state,
    state,
    [effect],
    [{
      type: "turn-transition",
      event: { type: "submit" },
      from: state.turnState,
      to: "streaming",
      statusLabel: COMPOSER_LOADING_STATUS,
    }],
    undefined,
    nextState,
  );
}

export interface EditRequest {
  messageIndex: number;
}

export function planEdit(state: ChatComposerState, request: EditRequest): ComposerPlan {
  if (!resolveTurnSession(state)) return rejected("edit", "no-session");
  if (state.turnState !== "idle") return rejected("edit", "turn-in-progress");
  if (!hasUsableMessageIndex(request.messageIndex)) return rejected("edit", "invalid-message-index");
  const message = findUserMessage(state, request.messageIndex);
  if (!message) return rejected("edit", "message-not-found");
  return acceptedPlan(
    "edit",
    state,
    state,
    [],
    [{
      type: "open-edit",
      messageIndex: request.messageIndex,
      messageId: message.id,
      text: message.content,
    }],
  );
}

export interface ForkRequest {
  messageIndex: number;
}

export function planFork(state: ChatComposerState, request: ForkRequest): ComposerPlan {
  const sessionId = resolveTurnSession(state);
  if (!sessionId) return rejected("fork", "no-session");
  if (state.turnState !== "idle") return rejected("fork", "turn-in-progress");
  if (!hasUsableMessageIndex(request.messageIndex)) return rejected("fork", "invalid-message-index");
  if (!findUserMessage(state, request.messageIndex)) return rejected("fork", "message-not-found");

  return acceptedPlan(
    "fork",
    state,
    state,
    [{ type: "fork-conversation", sessionId, fromMessageIndex: request.messageIndex }],
    [],
  );
}

export type ActionRequest =
  | { action: "send"; request: SendRequest }
  | { action: "redirect"; request: SendRequest }
  | { action: "stop" }
  | { action: "retry"; request: RetryRequest }
  | { action: "edit"; request: EditRequest }
  | { action: "fork"; request: ForkRequest };

export function planComposerAction(state: ChatComposerState, request: ActionRequest): ComposerPlan {
  switch (request.action) {
    case "send": return planSend(state, request.request);
    case "redirect": return planRedirectAction(state, request.request);
    case "stop": return planStop(state);
    case "retry": return planRetry(state, request.request);
    case "edit": return planEdit(state, request.request);
    case "fork": return planFork(state, request.request);
    default: return rejected("send", "unknown-action");
  }
}

/** Apply the optimistic state for plans whose effect is safe to expose immediately. */
export function applyOptimisticPlan(state: ChatComposerState, plan: ComposerPlan): ChatComposerState {
  return plan.accepted ? plan.optimisticState : state;
}

/** Apply a successful API effect, including retry's delayed transcript mutation. */
export function applySuccessfulPlan(
  state: ChatComposerState,
  plan: ComposerPlan,
  responseSessionId?: string | null,
): ChatComposerState {
  if (!plan.accepted) return state;
  const resolved = resolveResponseSession(plan.successState, responseSessionId);
  if (plan.action === "fork") {
    return {
      ...resolved,
      activeTurnSessionId: null,
      turnState: "idle",
      statusLabel: null,
      transcript: [],
    };
  }
  return resolved;
}

/** Roll back only the local optimistic state; transport errors do not mutate the transcript. */
export function rollbackFailedPlan(state: ChatComposerState, plan: ComposerPlan): ChatComposerState {
  return plan.accepted ? plan.rollbackState : state;
}
