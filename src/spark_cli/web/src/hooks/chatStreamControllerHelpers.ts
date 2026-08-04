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
