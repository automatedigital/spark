import { describe, expect, it } from "vitest";
import type { ContextItem } from "./context";
import type { ChatMessage } from "./chatTranscriptMerge";
import {
  COMPOSER_LOADING_STATUS,
  COMPOSER_REDIRECTING_STATUS,
  COMPOSER_STOPPING_STATUS,
  applyOptimisticPlan,
  applySuccessfulPlan,
  createComposerState,
  optimisticUserRow,
  planComposerAction,
  planFork,
  planRetry,
  planSend,
  planStop,
  retainedContextItems,
  resolveResponseSession,
  resolveTargetSession,
  resolveTurnSession,
  rollbackFailedPlan,
  truncateTranscriptForRetry,
} from "./chatComposerController";

const oneTurn: ContextItem = {
  id: "one-turn",
  type: "file",
  source_path: "/tmp/one.txt",
  inclusion_mode: "full",
  scope: "one_turn",
  size_bytes: 10,
};

const pinned: ContextItem = {
  id: "pinned",
  type: "file",
  source_path: "/tmp/pinned.txt",
  inclusion_mode: "path_only",
  scope: "pinned",
  size_bytes: 20,
};

function user(id: string, sessionIdx: number, content = id): ChatMessage {
  return { id, role: "user", sessionIdx, content };
}

function assistant(id: string, content = "answer"): ChatMessage {
  return { id, role: "assistant", content };
}

function baseState(overrides: Parameters<typeof createComposerState>[0] = {}) {
  return createComposerState({ sessionId: "session-1", ...overrides });
}

describe("chat composer controller", () => {
  it("resolves new, existing, active-turn, and workspace targets deterministically", () => {
    expect(resolveTargetSession({})).toEqual({ kind: "new", sessionId: null, workspaceSlug: null });
    expect(resolveTargetSession({ workspaceSlug: "project-a" })).toEqual({
      kind: "new", sessionId: null, workspaceSlug: "project-a",
    });
    expect(resolveTargetSession({ sessionId: "selected", activeSessionId: "active", workspaceSlug: "ignored" })).toEqual({
      kind: "existing", sessionId: "active", workspaceSlug: null,
    });
    expect(resolveTurnSession({ sessionId: "selected", activeTurnSessionId: "turn" })).toBe("turn");
    expect(resolveResponseSession(baseState(), "migrated").sessionId).toBe("migrated");
  });

  it("builds trimmed optimistic rows and keeps redirect/context metadata", () => {
    expect(optimisticUserRow({ id: "m1", text: "  hello  ", contextItems: [oneTurn], redirect: true })).toEqual({
      id: "m1", role: "user", content: "hello", contextItems: [oneTurn], redirect: true,
    });
    expect(retainedContextItems([oneTurn, pinned])).toEqual([pinned]);
  });

  it("plans an idle new-chat send with one-turn consumption and rollback", () => {
    const state = createComposerState({ contextItems: [oneTurn, pinned] });
    const plan = planSend(state, { messageId: "m1", text: " hello " });
    expect(plan.accepted).toBe(true);
    if (!plan.accepted) return;
    expect(plan.target).toEqual({ kind: "new", sessionId: null, workspaceSlug: null });
    expect(plan.effects).toEqual([{
      type: "start-conversation", message: "hello", contextItems: [oneTurn, pinned],
    }]);
    expect(plan.optimisticState.transcript).toEqual([optimisticUserRow({
      id: "m1", text: "hello", contextItems: [oneTurn, pinned],
    })]);
    expect(plan.optimisticState.contextItems).toEqual([pinned]);
    expect(plan.optimisticState.turnState).toBe("starting");
    expect(plan.optimisticState.statusLabel).toBe(COMPOSER_LOADING_STATUS);
    expect(rollbackFailedPlan(plan.optimisticState, plan)).toEqual(state);
  });

  it("plans an idle existing-session send", () => {
    const plan = planSend(baseState({ contextItems: [pinned] }), { messageId: "m2", text: "follow up" });
    expect(plan.accepted).toBe(true);
    if (!plan.accepted) return;
    expect(plan.effects).toEqual([{
      type: "post-conversation-message", sessionId: "session-1", message: "follow up", contextItems: [pinned],
    }]);
    expect(plan.optimisticState.transcript[0]).toMatchObject({ role: "user", content: "follow up" });
  });

  it("plans an idle workspace send without inventing a session id", () => {
    const plan = planSend(createComposerState(), {
      messageId: "m3", text: "build it", workspaceSlug: "project-a",
    });
    expect(plan.accepted).toBe(true);
    if (!plan.accepted) return;
    expect(plan.target).toEqual({ kind: "new", sessionId: null, workspaceSlug: "project-a" });
    expect(plan.effects).toEqual([{
      type: "start-workspace-conversation", workspaceSlug: "project-a", message: "build it", contextItems: [],
    }]);
  });

  it("turns an active send into one redirect and dedupes a second redirect", () => {
    const state = baseState({ turnState: "streaming", activeTurnSessionId: "turn-1" });
    const first = planSend(state, { messageId: "redirect-1", text: "change direction" });
    expect(first.accepted).toBe(true);
    if (!first.accepted) return;
    expect(first.action).toBe("redirect");
    expect(first.effects).toEqual([{
      type: "interrupt-conversation", sessionId: "turn-1", message: "change direction",
    }]);
    expect(first.optimisticState.transcript).toEqual([optimisticUserRow({
      id: "redirect-1", text: "change direction", redirect: true,
    })]);
    expect(first.optimisticState.statusLabel).toBe(COMPOSER_REDIRECTING_STATUS);
    const duplicate = planSend(first.optimisticState, { messageId: "redirect-2", text: "again" });
    expect(duplicate).toMatchObject({ accepted: false, action: "redirect", reason: "interrupt-in-flight" });
    expect(planComposerAction(baseState(), {
      action: "redirect", request: { messageId: "idle-redirect", text: "not active" },
    })).toMatchObject({ accepted: false, reason: "no-active-turn" });
  });

  it("dedupes stop while preserving the first stopping intent", () => {
    const state = baseState({ turnState: "streaming", activeTurnSessionId: "turn-2" });
    const first = planStop(state);
    expect(first.accepted).toBe(true);
    if (!first.accepted) return;
    expect(first.effects).toEqual([{ type: "interrupt-conversation", sessionId: "turn-2" }]);
    expect(first.optimisticState.turnState).toBe("stopping");
    expect(first.optimisticState.statusLabel).toBe(COMPOSER_STOPPING_STATUS);
    expect(planStop(first.optimisticState)).toMatchObject({ accepted: false, reason: "interrupt-in-flight" });
    expect(planStop(baseState())).toMatchObject({ accepted: false, reason: "no-active-turn" });
  });

  it("rejects empty sends before producing any effect", () => {
    expect(planSend(baseState(), { messageId: "empty", text: " \n " })).toMatchObject({
      accepted: false, action: "send", reason: "empty-message", effects: [], intents: [],
    });
  });

  it("truncates trailing retry work and edits only the targeted tail user row", () => {
    const transcript: ChatMessage[] = [
      user("u1", 4, "old prompt"),
      assistant("a1"),
      { id: "tool", role: "tool", toolId: "t1", name: "shell", args: {}, result: "ok" },
      { id: "reasoning", role: "reasoning", text: "thinking" },
      { id: "note", role: "note", text: "stale" },
    ];
    expect(truncateTranscriptForRetry(transcript, 4, "edited prompt")).toEqual([
      { ...transcript[0], content: "edited prompt" },
    ]);
    expect(truncateTranscriptForRetry([...transcript, user("u2", 5)], 4)).toEqual([...transcript, user("u2", 5)]);
  });

  it("guards retry, edit, and fork by session, turn, index, and user row", () => {
    const noSession = createComposerState({ transcript: [user("u", 1)] });
    expect(planRetry(noSession, { messageIndex: 1 })).toMatchObject({ accepted: false, reason: "no-session" });
    expect(planFork(noSession, { messageIndex: 1 })).toMatchObject({ accepted: false, reason: "no-session" });

    const streaming = baseState({ turnState: "streaming", transcript: [user("u", 1)] });
    expect(planRetry(streaming, { messageIndex: 1 })).toMatchObject({ accepted: false, reason: "turn-in-progress" });
    expect(planFork(streaming, { messageIndex: 1 })).toMatchObject({ accepted: false, reason: "turn-in-progress" });

    const idle = baseState({ transcript: [assistant("a"), user("u", 1)] });
    expect(planRetry(idle, { messageIndex: -1 })).toMatchObject({ accepted: false, reason: "invalid-message-index" });
    expect(planRetry(idle, { messageIndex: 9 })).toMatchObject({ accepted: false, reason: "message-not-found" });
    expect(planFork(idle, { messageIndex: 9 })).toMatchObject({ accepted: false, reason: "message-not-found" });
    const edit = planComposerAction(idle, { action: "edit", request: { messageIndex: 1 } });
    expect(edit).toMatchObject({ accepted: true, action: "edit" });
    if (edit.accepted) {
      expect(edit.intents).toEqual([{
        type: "open-edit", messageIndex: 1, messageId: "u", text: "u",
      }]);
    }
  });

  it("applies retry transcript changes only after the API effect succeeds", () => {
    const state = baseState({ transcript: [user("u", 2, "before"), assistant("a")] });
    const plan = planRetry(state, { messageIndex: 2, editedText: "after" });
    expect(plan.accepted).toBe(true);
    if (!plan.accepted) return;
    expect(plan.optimisticState).toEqual(state);
    expect(plan.successState.transcript).toEqual([{ ...state.transcript[0], content: "after" }]);
    expect(plan.successState.turnState).toBe("streaming");
    expect(plan.effects).toEqual([{
      type: "retry-conversation", sessionId: "session-1", messageIndex: 2, message: "after",
    }]);
    expect(applySuccessfulPlan(state, plan).transcript).toEqual(plan.successState.transcript);
    expect(rollbackFailedPlan(state, plan)).toEqual(state);
  });

  it("plans fork as an effect and clears the local transcript only after success", () => {
    const state = baseState({ transcript: [user("u", 3), assistant("a")] });
    const plan = planFork(state, { messageIndex: 3 });
    expect(plan.accepted).toBe(true);
    if (!plan.accepted) return;
    expect(plan.effects).toEqual([{
      type: "fork-conversation", sessionId: "session-1", fromMessageIndex: 3,
    }]);
    expect(plan.optimisticState).toEqual(state);
    expect(applySuccessfulPlan(state, plan, "forked")).toMatchObject({
      sessionId: "forked", activeTurnSessionId: null, turnState: "idle", transcript: [],
    });
    expect(rollbackFailedPlan(state, plan)).toEqual(state);
  });

  it("keeps controller functions deterministic and does not mutate caller state", () => {
    const state = baseState({ contextItems: [oneTurn, pinned], transcript: [user("u", 1)] });
    const before = JSON.parse(JSON.stringify(state));
    const first = planSend(state, { messageId: "m", text: "hello" });
    const second = planSend(state, { messageId: "m", text: "hello" });
    expect(second).toEqual(first);
    expect(state).toEqual(before);
    expect(applyOptimisticPlan(state, first)).not.toBe(state);
  });
});
