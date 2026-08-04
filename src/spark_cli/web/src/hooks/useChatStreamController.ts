import { useCallback, useEffect, useRef, useState } from "react";
import {
  createChatStreamState,
  type ChatStreamAction,
  type ChatStreamEvent,
  type ChatStreamSnapshot,
  type ChatStreamState,
  type FlushReason,
} from "@/lib/chatStreamReducer";
import type { ChatMessage } from "@/lib/chatTranscriptMerge";
import { liveStreamFlushInterval } from "@/lib/liveStreamWindow";
import {
  executeChatStreamEffect,
  eventAction,
  flushAction,
  isCurrentChatStreamEffect,
  reduceChatStreamController,
  snapshotAction,
  type ChatStreamControllerCallbacks,
  type ChatStreamControllerTransition,
  type ChatStreamSessionInput,
  type QueuedChatStreamEffect,
} from "./chatStreamControllerHelpers";

export type {
  ChatStreamControllerCallbacks,
  ChatStreamHistoryRequest,
  ChatStreamResyncRequest,
  ChatStreamSessionInput,
  QueuedChatStreamEffect,
} from "./chatStreamControllerHelpers";

export interface UseChatStreamControllerOptions {
  activeSessionId: string | null;
  recoverySequence?: number;
  sessionAliases?: readonly string[];
  initialMessages?: readonly ChatMessage[];
  messageIdPrefix?: string;
  callbacks?: ChatStreamControllerCallbacks;
}

export interface UseChatStreamControllerResult {
  state: ChatStreamState;
  handleEvent: (event: ChatStreamEvent) => ChatStreamControllerTransition;
  applySnapshot: (snapshot: ChatStreamSnapshot) => ChatStreamControllerTransition;
  flush: (reason?: FlushReason) => ChatStreamControllerTransition;
  finalize: () => ChatStreamControllerTransition;
  syncMessages: (messages: readonly ChatMessage[]) => ChatStreamControllerTransition;
  setSession: (input: ChatStreamSessionInput) => ChatStreamControllerTransition;
  resetSession: (input?: Partial<ChatStreamSessionInput>) => ChatStreamControllerTransition;
  reset: (input?: Partial<ChatStreamSessionInput>) => ChatStreamControllerTransition;
}

interface QueuedEffectBatch {
  effects: readonly QueuedChatStreamEffect[];
  revision: number;
}

function initialState(options: UseChatStreamControllerOptions): ChatStreamState {
  return createChatStreamState({
    sessionId: options.activeSessionId,
    aliases: options.sessionAliases,
    recoverySequence: options.recoverySequence,
    messages: options.initialMessages,
    messageIdPrefix: options.messageIdPrefix,
  });
}

function sameSessionConfig(
  left: { sessionId: string | null; recoverySequence: number },
  right: { sessionId: string | null; recoverySequence: number },
): boolean {
  return left.sessionId === right.sessionId && left.recoverySequence === right.recoverySequence;
}

export function useChatStreamController(
  options: UseChatStreamControllerOptions,
): UseChatStreamControllerResult {
  const [state, setState] = useState(() => initialState(options));
  const stateRef = useRef(state);
  const configRef = useRef({
    sessionId: options.activeSessionId,
    recoverySequence: options.recoverySequence ?? 0,
  });
  const callbacksRef = useRef(options.callbacks);
  const effectQueueRef = useRef<QueuedEffectBatch>({ effects: [], revision: 0 });
  const [effectRevision, setEffectRevision] = useState(0);
  const mountedRef = useRef(false);
  const flushTimerRef = useRef<number | null>(null);
  const flushRafRef = useRef<number | null>(null);

  callbacksRef.current = options.callbacks;

  const commit = useCallback((transition: ChatStreamControllerTransition): ChatStreamControllerTransition => {
    stateRef.current = transition.state;
    setState(transition.state);
    callbacksRef.current?.onStateChange?.(transition);
    if (transition.queuedEffects.length > 0) {
      const nextRevision = effectQueueRef.current.revision + 1;
      effectQueueRef.current = {
        effects: [...effectQueueRef.current.effects, ...transition.queuedEffects],
        revision: nextRevision,
      };
      setEffectRevision(nextRevision);
    }
    return transition;
  }, []);

  const dispatch = useCallback((action: ChatStreamAction): ChatStreamControllerTransition => (
    commit(reduceChatStreamController(stateRef.current, action))
  ), [commit]);

  const applySnapshot = useCallback((snapshot: ChatStreamSnapshot) => dispatch(snapshotAction(snapshot)), [dispatch]);
  const clearScheduledFlush = useCallback(() => {
    if (flushTimerRef.current !== null) window.clearTimeout(flushTimerRef.current);
    if (flushRafRef.current !== null) window.cancelAnimationFrame(flushRafRef.current);
    flushTimerRef.current = null;
    flushRafRef.current = null;
  }, []);
  const flush = useCallback((reason?: FlushReason) => {
    clearScheduledFlush();
    return dispatch(flushAction(reason));
  }, [clearScheduledFlush, dispatch]);
  const finalize = useCallback(() => {
    clearScheduledFlush();
    return dispatch({ type: "finalize" });
  }, [clearScheduledFlush, dispatch]);
  const syncMessages = useCallback((messages: readonly ChatMessage[]) => (
    dispatch({ type: "sync-messages", messages })
  ), [dispatch]);

  const scheduleBufferedFlush = useCallback(() => {
    if (flushTimerRef.current !== null || flushRafRef.current !== null) return;
    const delay = liveStreamFlushInterval(stateRef.current.streamTextChars + stateRef.current.tokenBuffer.length);
    flushTimerRef.current = window.setTimeout(() => {
      flushTimerRef.current = null;
      flushRafRef.current = window.requestAnimationFrame(() => {
        flushRafRef.current = null;
        flush("manual");
      });
    }, delay);
  }, [flush]);

  // Token and reasoning deltas update the reducer's mutable transition state,
  // but do not commit a React render until the scheduled visible flush. This
  // preserves the previous stream throughput while keeping every topic in the
  // reducer seam.
  const handleEvent = useCallback((event: ChatStreamEvent) => {
    if (event.topic !== "chat.token" && event.topic !== "chat.reasoning") {
      return dispatch(eventAction(event));
    }
    const transition = reduceChatStreamController(stateRef.current, eventAction(event));
    stateRef.current = transition.state;
    if (transition.accepted) scheduleBufferedFlush();
    return transition;
  }, [dispatch, scheduleBufferedFlush]);

  const setSession = useCallback((input: ChatStreamSessionInput): ChatStreamControllerTransition => {
    const transition = dispatch({
      type: "set-session",
      sessionId: input.sessionId,
      aliases: input.aliases,
      recoverySequence: input.recoverySequence,
      messages: input.messages,
    });
    configRef.current = {
      sessionId: input.sessionId,
      recoverySequence: transition.state.recoverySequence,
    };
    return transition;
  }, [dispatch]);

  const resetSession = useCallback((input: Partial<ChatStreamSessionInput> = {}): ChatStreamControllerTransition => {
    const current = stateRef.current;
    return setSession({
      sessionId: input.sessionId === undefined ? current.activeSessionId : input.sessionId,
      aliases: input.aliases ?? current.sessionAliases,
      recoverySequence: input.recoverySequence ?? current.recoverySequence + 1,
      messages: input.messages,
    });
  }, [setSession]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearScheduledFlush();
    };
  }, [clearScheduledFlush]);

  useEffect(() => {
    const nextConfig = {
      sessionId: options.activeSessionId,
      recoverySequence: options.recoverySequence ?? 0,
    };
    if (sameSessionConfig(configRef.current, nextConfig)) return;
    configRef.current = nextConfig;
    commit(reduceChatStreamController(stateRef.current, {
      type: "set-session",
      sessionId: nextConfig.sessionId,
      aliases: options.sessionAliases,
      recoverySequence: nextConfig.recoverySequence,
      // Session recovery calls setSession with the authoritative transcript
      // before this config effect runs. Preserve that reducer state instead of
      // re-seeding it from the render's potentially stale prop snapshot.
      messages: stateRef.current.activeSessionId === nextConfig.sessionId
        ? stateRef.current.messages
        : options.initialMessages,
    }));
  }, [commit, options.activeSessionId, options.initialMessages, options.recoverySequence, options.sessionAliases]);

  useEffect(() => {
    const queued = effectQueueRef.current;
    if (queued.revision !== effectRevision || queued.effects.length === 0) return;
    effectQueueRef.current = { effects: [], revision: queued.revision };
    for (const effect of queued.effects) {
      if (!mountedRef.current || !isCurrentChatStreamEffect(effect, stateRef.current)) continue;
      try {
        const result = executeChatStreamEffect(effect, callbacksRef.current ?? {});
        if (result && typeof result.then === "function") {
          void result.catch((error: unknown) => callbacksRef.current?.onEffectError?.(error, effect));
        }
      } catch (error) {
        callbacksRef.current?.onEffectError?.(error, effect);
      }
    }
  }, [effectRevision]);

  return {
    state,
    handleEvent,
    applySnapshot,
    flush,
    finalize,
    syncMessages,
    setSession,
    resetSession,
    reset: resetSession,
  };
}
