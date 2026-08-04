import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import { api as defaultApi } from "@/lib/api";
import type { ContextItem } from "@/lib/context";
import type { ChatMessage } from "@/lib/chatTranscriptMerge";
import {
  createComposerState,
  planComposerAction,
  rollbackFailedPlan,
  type AcceptedComposerPlan,
  type ComposerEffect,
  type ComposerPlan,
} from "@/lib/chatComposerController";
import type { ChatTurnState } from "@/lib/chatTurnState";

export interface ComposerApi {
  postConversation: (
    message: string,
    model?: string,
    contextItems?: unknown[],
    source?: string | null,
  ) => Promise<{ session_id: string; ok: boolean }>;
  postConversationMessage: (
    sessionId: string,
    message: string,
    contextItems?: unknown[],
  ) => Promise<{ session_id: string; ok: boolean }>;
  startWorkspaceConversation: (
    slug: string,
    message: string,
    model?: string,
    contextItems?: unknown[],
  ) => Promise<{ session_id: string; ok: boolean; source: string }>;
  interruptConversation: (
    sessionId: string,
    message?: string,
  ) => Promise<unknown>;
}

export interface ComposerEffectRunner {
  apiClient?: ComposerApi;
  retry: (messageIndex: number, message?: string) => Promise<void>;
  fork: (fromMessageIndex?: number) => Promise<void>;
}

export async function executeComposerEffect(
  effect: ComposerEffect,
  runner: ComposerEffectRunner,
): Promise<unknown> {
  const client = runner.apiClient ?? defaultApi;
  switch (effect.type) {
    case "start-conversation":
      return client.postConversation(effect.message, undefined, effect.contextItems);
    case "start-workspace-conversation":
      return client.startWorkspaceConversation(effect.workspaceSlug, effect.message, undefined, effect.contextItems);
    case "post-conversation-message":
      return client.postConversationMessage(effect.sessionId, effect.message, effect.contextItems);
    case "interrupt-conversation":
      return client.interruptConversation(effect.sessionId, effect.message);
    case "retry-conversation":
      await runner.retry(effect.messageIndex, effect.message);
      return undefined;
    case "fork-conversation":
      await runner.fork(effect.fromMessageIndex);
      return undefined;
  }
}

export interface ComposerIntentHandlers {
  setTurnState: (state: ChatTurnState) => void;
  setStatusLabel: (label: string | null) => void;
  appendUserRow: (row: ChatMessage) => void;
  retainContext: (items: ContextItem[]) => void;
  openEdit: (messageIndex: number, text: string) => void;
}

export function applyComposerPlanIntents(
  plan: ComposerPlan,
  handlers: ComposerIntentHandlers,
): void {
  if (!plan.accepted) return;
  for (const intent of plan.intents) {
    switch (intent.type) {
      case "turn-transition":
        handlers.setTurnState(intent.to);
        handlers.setStatusLabel(intent.statusLabel);
        break;
      case "append-user-row":
        handlers.appendUserRow(intent.row);
        break;
      case "retain-context":
        handlers.retainContext(intent.after);
        break;
      case "open-edit":
        handlers.openEdit(intent.messageIndex, intent.text);
        break;
    }
  }
}

export interface UseChatComposerActionsOptions {
  input: string;
  contextItems: ContextItem[];
  transcript: ChatMessage[];
  activeSessionId: string | null;
  activeTurnSessionIdRef: MutableRefObject<string | null>;
  activeSessionRef: MutableRefObject<string | null>;
  rememberActiveSessionAliases: (...ids: Array<string | null | undefined>) => void;
  turnState: ChatTurnState;
  turnStateRef: MutableRefObject<ChatTurnState>;
  statusLabel: string | null;
  workspaceSlug?: string;
  setInput: Dispatch<SetStateAction<string>>;
  setContextItems: Dispatch<SetStateAction<ContextItem[]>>;
  setChatMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  setActiveSessionId: Dispatch<SetStateAction<string | null>>;
  setTurnState: Dispatch<SetStateAction<ChatTurnState>>;
  setStatusLabel: Dispatch<SetStateAction<string | null>>;
  setError: Dispatch<SetStateAction<string | null>>;
  createMessageId: () => string;
  onSessionCreated?: (
    id: string,
    initialMessage?: string,
    meta?: { source?: string | null; projectSlug?: string | null },
  ) => void;
  onPrepareSend?: (optimisticMessageCount: number) => void;
  onEdit: (messageIndex: number, text: string) => void;
  retryAction: (messageIndex: number, edited?: string) => Promise<void>;
  forkAction: (fromMessageIndex?: number) => Promise<void>;
  resyncTurnState: (options?: { allowIdle?: boolean }) => Promise<void>;
  apiClient?: ComposerApi;
}

function errorText(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message.replace(/^\d+:\s*/, "");
}

export function useChatComposerActions({
  input,
  contextItems,
  transcript,
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
  createMessageId,
  onSessionCreated,
  onPrepareSend,
  onEdit,
  retryAction,
  forkAction,
  resyncTurnState,
  apiClient,
}: UseChatComposerActionsOptions) {
  const setTurn = useCallback((next: ChatTurnState) => {
    turnStateRef.current = next;
    setTurnState(next);
  }, [setTurnState, turnStateRef]);

  const state = useCallback(() => createComposerState({
    sessionId: activeSessionRef.current ?? activeSessionId,
    activeTurnSessionId: activeTurnSessionIdRef.current,
    turnState: turnStateRef.current || turnState,
    statusLabel,
    transcript,
    contextItems,
  }), [
    activeSessionId,
    activeSessionRef,
    activeTurnSessionIdRef,
    contextItems,
    statusLabel,
    transcript,
    turnState,
    turnStateRef,
  ]);

  const applyIntents = useCallback((plan: ComposerPlan) => {
    applyComposerPlanIntents(plan, {
      setTurnState: setTurn,
      setStatusLabel,
      appendUserRow: (row) => setChatMessages((previous) => [...previous, row]),
      retainContext: (items) => setContextItems(items),
      openEdit: onEdit,
    });
  }, [onEdit, setChatMessages, setContextItems, setStatusLabel, setTurn]);

  const runner = useCallback((): ComposerEffectRunner => ({
    apiClient,
    retry: retryAction,
    fork: forkAction,
  }), [apiClient, forkAction, retryAction]);

  const updateSessionFromResponse = useCallback((
    plan: AcceptedComposerPlan,
    result: unknown,
  ) => {
    if (plan.action !== "send" || !result || typeof result !== "object") return;
    const response = result as { session_id?: unknown; source?: unknown };
    if (typeof response.session_id !== "string" || !response.session_id) return;

    const previousSessionId = activeSessionRef.current ?? activeSessionId;
    rememberActiveSessionAliases(previousSessionId, response.session_id);
    if (previousSessionId !== response.session_id) {
      activeSessionRef.current = response.session_id;
      setActiveSessionId(response.session_id);
    }
    if (plan.target?.kind === "new" || response.session_id !== plan.target?.sessionId) {
      const effect = plan.effects[0];
      onSessionCreated?.(
        response.session_id,
        effect && "message" in effect ? effect.message : undefined,
        effect?.type === "start-workspace-conversation"
          ? {
              source: typeof response.source === "string" ? response.source : null,
              projectSlug: effect.workspaceSlug,
            }
          : undefined,
      );
    }
  }, [activeSessionId, activeSessionRef, onSessionCreated, rememberActiveSessionAliases, setActiveSessionId]);

  const executePlan = useCallback(async (
    plan: ComposerPlan,
    previousState: ReturnType<typeof createComposerState>,
    options: { applyIntents?: boolean; rollbackOnError?: boolean } = {},
  ): Promise<boolean> => {
    if (!plan.accepted) return false;
    if (options.applyIntents !== false) applyIntents(plan);
    const effect = plan.effects[0];
    if (!effect) return true;
    try {
      const result = await executeComposerEffect(effect, runner());
      updateSessionFromResponse(plan, result);
      return true;
    } catch (error) {
      if (options.rollbackOnError) {
        const rollback = rollbackFailedPlan(previousState, plan);
        setChatMessages(rollback.transcript.slice());
        setContextItems(rollback.contextItems.slice());
        setTurn(rollback.turnState);
        setStatusLabel(rollback.statusLabel);
        setError(errorText(error));
      }
      return false;
    }
  }, [applyIntents, runner, setChatMessages, setContextItems, setError, setStatusLabel, setTurn, updateSessionFromResponse]);

  const sendMessage = useCallback(async () => {
    const previousState = state();
    const plan = planComposerAction(previousState, {
      action: "send",
      request: {
        messageId: createMessageId(),
        text: input,
        workspaceSlug,
      },
    });
    if (!plan.accepted) return;

    if (plan.action === "send") {
      setInput("");
      setError(null);
      applyIntents(plan);
      if (input.trim() === "/feedback") {
        setChatMessages((previous) => [...previous, { id: createMessageId(), role: "feedback_form" }]);
      }
      onPrepareSend?.(plan.optimisticState.transcript.length);
      await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
      await executePlan(plan, previousState, { applyIntents: false, rollbackOnError: true });
      return;
    }

    applyIntents(plan);
    try {
      await executeComposerEffect(plan.effects[0]!, runner());
      setInput("");
    } catch {
      setStatusLabel("Redirect requested; waiting for backend state…");
      void resyncTurnState();
    }
  }, [applyIntents, createMessageId, executePlan, input, onPrepareSend, resyncTurnState, runner, setError, setInput, setChatMessages, setStatusLabel, state, workspaceSlug]);

  const stop = useCallback(async () => {
    const previousState = state();
    const plan = planComposerAction(previousState, { action: "stop" });
    if (!plan.accepted) return;
    applyIntents(plan);
    try {
      await executeComposerEffect(plan.effects[0]!, runner());
    } catch {
      setStatusLabel("Stop requested; waiting for backend state…");
      void resyncTurnState();
    }
  }, [applyIntents, resyncTurnState, runner, setStatusLabel, state]);

  const retryMessage = useCallback(async (messageIndex: number, edited?: string) => {
    const previousState = state();
    const plan = planComposerAction(previousState, {
      action: "retry",
      request: { messageIndex, ...(edited !== undefined ? { editedText: edited } : {}) },
    });
    await executePlan(plan, previousState, { applyIntents: false });
  }, [executePlan, state]);

  const editMessage = useCallback((messageIndex: number) => {
    const plan = planComposerAction(state(), { action: "edit", request: { messageIndex } });
    applyIntents(plan);
  }, [applyIntents, state]);

  const forkMessage = useCallback(async (messageIndex: number) => {
    const previousState = state();
    const plan = planComposerAction(previousState, { action: "fork", request: { messageIndex } });
    await executePlan(plan, previousState, { applyIntents: false });
  }, [executePlan, state]);

  const forkSession = useCallback(async () => {
    await forkAction();
  }, [forkAction]);

  return { sendMessage, stop, retryMessage, editMessage, forkMessage, forkSession };
}
