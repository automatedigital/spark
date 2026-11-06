import {
  reduceChatStream,
  type ChatStreamAction,
  type ChatStreamEffect,
  type ChatStreamEvent,
  type ChatStreamSnapshot,
  type ChatStreamState,
  type ChatStreamTransition,
  type FlushReason,
} from "@/lib/chatStreamReducer";
import type { ChatMessage } from "@/lib/chatTranscriptMerge";

export interface ChatStreamSessionInput {
  sessionId: string | null;
  aliases?: readonly string[];
  recoverySequence?: number;
  messages?: readonly ChatMessage[];
}

export interface ChatStreamEffectContext {
  sessionId: string | null;
  recoverySequence: number;
}

export interface QueuedChatStreamEffect extends ChatStreamEffectContext {
  effect: ChatStreamEffect;
}

export interface ChatStreamResyncRequest extends ChatStreamEffectContext {
  reason: Extract<ChatStreamEffect, { type: "resync" }>['reason'];
  allowIdle: boolean;
}

export interface ChatStreamHistoryRequest extends ChatStreamEffectContext {
  sessionId: string;
  reason: Extract<ChatStreamEffect, { type: "load-history" }>['reason'];
}

export interface ChatStreamControllerCallbacks {
  onStateChange?: (transition: ChatStreamControllerTransition) => void;
  onFlushStream?: (reason: FlushReason) => void | Promise<void>;
  onResync?: (request: ChatStreamResyncRequest) => void | Promise<void>;
  onLoadHistory?: (request: ChatStreamHistoryRequest) => void | Promise<void>;
  onEffectError?: (error: unknown, effect: QueuedChatStreamEffect) => void;
}

export interface ChatStreamControllerTransition extends ChatStreamTransition {
  queuedEffects: readonly QueuedChatStreamEffect[];
}

/** A confirmed same-owner ID handoff is an alias change, not session recovery. */
export function adoptChatStreamSession(
  state: ChatStreamState,
  sessionId: string,
  aliases: readonly string[] = [],
): ChatStreamControllerTransition {
  return {
    state: { ...state, activeSessionId: sessionId, sessionAliases: [...new Set([...state.sessionAliases, ...aliases, sessionId])] },
    effects: [], queuedEffects: [], accepted: true,
  };
}

function effectSessionId(effect: ChatStreamEffect, state: ChatStreamState): string | null {
  return effect.type === "load-history" ? effect.sessionId : state.activeSessionId;
}

export function queueChatStreamEffects(
  effects: readonly ChatStreamEffect[],
  state: ChatStreamState,
): readonly QueuedChatStreamEffect[] {
  return effects.map((effect) => ({
    effect,
    sessionId: effectSessionId(effect, state),
    recoverySequence: state.recoverySequence,
  }));
}

export function reduceChatStreamController(
  state: ChatStreamState,
  action: ChatStreamAction,
): ChatStreamControllerTransition {
  const transition = reduceChatStream(state, action);
  return {
    ...transition,
    queuedEffects: queueChatStreamEffects(transition.effects, transition.state),
  };
}

export function isCurrentChatStreamEffect(
  queuedEffect: QueuedChatStreamEffect,
  state: ChatStreamState,
): boolean {
  if (queuedEffect.recoverySequence !== state.recoverySequence) return false;
  if (!queuedEffect.sessionId) return state.activeSessionId === null;
  return state.sessionAliases.includes(queuedEffect.sessionId);
}

export function executeChatStreamEffect(
  queuedEffect: QueuedChatStreamEffect,
  callbacks: ChatStreamControllerCallbacks,
): void | Promise<void> {
  const { effect } = queuedEffect;
  switch (effect.type) {
    case "flush-stream":
      return callbacks.onFlushStream?.(effect.reason);
    case "resync":
      return callbacks.onResync?.({
        reason: effect.reason,
        allowIdle: effect.allowIdle,
        sessionId: queuedEffect.sessionId,
        recoverySequence: queuedEffect.recoverySequence,
      });
    case "load-history":
      return callbacks.onLoadHistory?.({
        sessionId: effect.sessionId,
        reason: effect.reason,
        recoverySequence: queuedEffect.recoverySequence,
      });
  }
}

export function eventAction(event: ChatStreamEvent): ChatStreamAction {
  return { type: "event", event };
}

export function snapshotAction(snapshot: ChatStreamSnapshot): ChatStreamAction {
  return { type: "reconnect-snapshot", snapshot };
}

export function flushAction(reason?: FlushReason): ChatStreamAction {
  return { type: "flush", ...(reason === undefined ? {} : { reason }) };
}

/** History has already been reconciled; restore its independent bounded live tail.
 * A full tail is authoritative even when its revision equals the last delivery.
 * Do not replace tokens received after this snapshot was assembled.
 */
export function hydrateChatStreamRecovery(
  state: ChatStreamState,
  snapshot: ChatStreamSnapshot,
): ChatStreamControllerTransition {
  if (!snapshot.turn_active) {
    const transition = reduceChatStreamController(state, snapshotAction(snapshot));
    if (!transition.accepted) return transition;
    // The authoritative response already supplied saved history. Complete the
    // reducer reconciliation too, without the legacy follow-up history fetch.
    return {
      ...transition,
      state: { ...transition.state, turnState: "idle", statusLabel: null, finalized: true },
      effects: [], queuedEffects: [],
    };
  }
  if ((snapshot.stream_revision ?? 0) < state.streamRevision) {
    return { state, effects: [], queuedEffects: [], accepted: false };
  }
  return reduceChatStreamController({
    ...state, streamRevision: 0, streamTextChars: 0, tokenBuffer: "",
  }, snapshotAction(snapshot));
}
