import { describe, expect, it } from "vitest";
import {
  createChatStreamState,
  reduceChatStream,
  type ChatStreamEvent,
} from "./chatStreamReducer";
import type { ChatMessage } from "./chatTranscriptMerge";

function event(topic: string, data: Record<string, unknown> = {}, sessionId = "s1", sequence?: number): ChatStreamEvent {
  return { topic, data, session_id: sessionId, ...(sequence === undefined ? {} : { sequence }) };
}

function reduce(state: ReturnType<typeof createChatStreamState>, next: ChatStreamEvent) {
  return reduceChatStream(state, { type: "event", event: next });
}

describe("chatStreamReducer", () => {
  it("rejects events for another session and duplicate or out-of-order sequences", () => {
    const initial = createChatStreamState({ sessionId: "s1" });
    const foreign = reduce(initial, event("chat.token", { t: "bad" }, "s2", 1));
    expect(foreign.accepted).toBe(false);
    expect(foreign.state.tokenBuffer).toBe("");

    const accepted = reduce(initial, event("chat.token", { t: "ok" }, "s1", 4));
    const duplicate = reduce(accepted.state, event("chat.token", { t: "ignored" }, "s1", 4));
    expect(accepted.accepted).toBe(true);
    expect(duplicate.accepted).toBe(false);
    expect(duplicate.state.tokenBuffer).toBe("ok");
  });

  it("buffers tokens and reasoning until an explicit flush", () => {
    const initial = createChatStreamState({ sessionId: "s1" });
    const token = reduce(initial, event("chat.token", { t: "hello " }));
    const reasoning = reduce(token.state, event("chat.reasoning", { text: "think" }));
    expect(reasoning.state.messages).toHaveLength(0);
    expect(reasoning.state.tokenBuffer).toBe("hello ");
    expect(reasoning.state.reasoningBuffer).toBe("think");

    const flushed = reduceChatStream(reasoning.state, { type: "flush", reason: "manual" });
    expect(flushed.state.messages.map((message) => message.role)).toEqual(["assistant", "reasoning"]);
    expect(flushed.state.messages[0]).toMatchObject({ role: "assistant", content: "hello ", streaming: true });
    expect(flushed.state.messages[1]).toMatchObject({ role: "reasoning", text: "think" });
    expect(flushed.state.tokenBuffer).toBe("");
    expect(flushed.state.reasoningBuffer).toBe("");
  });

  it("keeps every token delta when several events arrive before one visible flush", () => {
    let state = createChatStreamState({ sessionId: "s1" });
    for (const token of ["one ", "two ", "three"]) {
      state = reduce(state, event("chat.token", { t: token })).state;
    }

    expect(state.messages).toHaveLength(0);
    expect(state.tokenBuffer).toBe("one two three");

    const flushed = reduceChatStream(state, { type: "flush", reason: "manual" });
    expect(flushed.state.messages[0]).toMatchObject({
      role: "assistant",
      content: "one two three",
      liveTotalChars: 13,
    });
  });

  it("syncs authoritative history without clearing live reducer metadata", () => {
    const initial = reduce(
      createChatStreamState({ sessionId: "s1" }),
      event("chat.token", { t: "partial" }),
    ).state;
    const history = [{ id: "db:u1", role: "user", content: "saved" } satisfies ChatMessage];
    const synced = reduceChatStream(initial, { type: "sync-messages", messages: history });

    expect(synced.state.messages).toEqual(history);
    expect(synced.state.tokenBuffer).toBe("partial");
    expect(synced.state.activeSessionId).toBe("s1");
  });

  it("flushes and finalizes the assistant before a tool, then updates that tool by id", () => {
    const initial = createChatStreamState({
      sessionId: "s1",
      messages: [{ id: "u1", role: "user", content: "run it" } satisfies ChatMessage],
    });
    const token = reduce(initial, event("chat.token", { t: "before tool" }));
    const started = reduce(token.state, event("chat.tool_start", {
      id: "tool-1",
      name: "shell",
      args: { command: "pwd" },
      started_at: 10,
    }));
    expect(started.state.messages).toHaveLength(3);
    expect(started.state.messages[1]).toMatchObject({ role: "assistant", content: "before tool", streaming: false });
    expect(started.state.messages[2]).toMatchObject({ role: "tool", toolId: "tool-1", done: false });
    expect(started.effects).toContainEqual({ type: "flush-stream", reason: "tool-start" });

    const ended = reduce(started.state, event("chat.tool_end", {
      id: "tool-1", result_preview: "ok", result_truncated: true, ended_at: 12, duration_seconds: 2,
    }));
    expect(ended.state.messages[2]).toMatchObject({
      role: "tool", result: "ok", done: true, resultTruncated: true, durationSeconds: 2,
    });
  });

  it("tracks approval and requested-input pauses without losing the transcript", () => {
    const initial = createChatStreamState({ sessionId: "s1" });
    const approval = reduce(initial, event("chat.approval_requested", {
      approval: { command: "rm -i file" },
    }));
    expect(approval.state.turnState).toBe("awaiting-approval");
    expect(approval.state.pendingApproval).toBe(true);
    expect(approval.state.messages.at(-1)?.role).toBe("approval");

    const resolved = reduce(approval.state, event("chat.approval_resolved"));
    expect(resolved.state.pendingApproval).toBe(false);
    expect(resolved.state.messages.at(-1)).toMatchObject({ role: "approval", resolved: true });

    const requested = reduce(resolved.state, event("chat.input_requested", {
      input: { id: "question-1", prompt: "Which environment?", fields: ["environment"] },
    }));
    expect(requested.state.turnState).toBe("awaiting-input");
    expect(requested.state.pendingInput).toMatchObject({ id: "question-1", prompt: "Which environment?" });

    const answered = reduce(requested.state, event("chat.input_resolved", { id: "question-1" }));
    expect(answered.state.pendingInput).toBeNull();
    expect(answered.state.turnState).toBe("streaming");
  });

  it("preserves migration aliases so old and new session events remain guarded", () => {
    const initial = createChatStreamState({ sessionId: "old" });
    const migrated = reduce(initial, event("chat.session_migrated", {
      old_session_id: "old",
      new_session_id: "new",
    }, "old"));
    expect(migrated.state.activeSessionId).toBe("new");
    expect(migrated.state.sessionAliases).toEqual(["old", "new"]);

    const oldEvent = reduce(migrated.state, event("chat.token", { t: "from alias" }, "old"));
    const foreign = reduce(migrated.state, event("chat.token", { t: "blocked" }, "other"));
    expect(oldEvent.accepted).toBe(true);
    expect(oldEvent.state.tokenBuffer).toBe("from alias");
    expect(foreign.accepted).toBe(false);
  });

  it("emits authoritative finalization/history effects and attaches usage", () => {
    const initial = createChatStreamState({ sessionId: "s1" });
    const streaming = reduce(initial, event("chat.token", { t: "answer" }));
    const done = reduce(streaming.state, event("chat.turn_done", {
      session_id: "s1",
      model: "gpt-test",
      tokens: { input: 10, output: 5, cache_read: 3, cache_write: 1 },
      cost_usd: 0.02,
      final_assistant_present: true,
    }));
    expect(done.state.turnState).toBe("idle");
    expect(done.state.finalized).toBe(true);
    expect(done.state.messages[0]).toMatchObject({ role: "assistant", content: "answer", streaming: false });
    expect(done.state.messages[0]).toMatchObject({ usage: { totalTokens: 15, costUsd: 0.02 } });
    expect(done.state.stats).toMatchObject({ model: "gpt-test", inputTokens: 10, outputTokens: 5, turnCount: 1 });
    expect(done.effects).toContainEqual({ type: "load-history", sessionId: "s1", reason: "turn-done" });
  });

  it("represents interruption and failure as terminal state while requesting reconciliation", () => {
    const interrupted = reduce(
      reduce(createChatStreamState({ sessionId: "s1" }), event("chat.token", { t: "partial" })).state,
      event("chat.interrupted", { message: "user stopped", phase: "stopping" }),
    );
    expect(interrupted.state.turnState).toBe("stopping");
    expect(interrupted.state.interrupted).toBe(true);
    expect(interrupted.effects).toContainEqual({ type: "resync", reason: "interrupted", allowIdle: false });

    const failed = reduce(interrupted.state, event("chat.failed", { error: "provider timeout" }));
    expect(failed.state.turnState).toBe("failed");
    expect(failed.state.failed).toBe(true);
    expect(failed.state.error).toBe("provider timeout");
    expect(failed.effects).toContainEqual({ type: "load-history", sessionId: "s1", reason: "failure" });
  });

  it("uses reconnect snapshots as an authoritative, revision-guarded stream source", () => {
    const initial = createChatStreamState({ sessionId: "s1" });
    const active = reduceChatStream(initial, {
      type: "reconnect-snapshot",
      snapshot: {
        session_id: "s1",
        active_turn_session_id: "s1",
        turn_active: true,
        stream_text: "hello",
        stream_revision: 2,
        stream_text_chars: 5,
      },
    });
    expect(active.state.messages[0]).toMatchObject({ role: "assistant", content: "hello", streaming: true });
    expect(active.state.streamRevision).toBe(2);

    const delta = reduceChatStream(active.state, {
      type: "reconnect-snapshot",
      snapshot: {
        session_id: "s1",
        active_turn_session_id: "s1",
        turn_active: true,
        stream_text: " world",
        stream_text_start: 5,
        stream_text_chars: 11,
        stream_revision: 3,
      },
    });
    expect(delta.state.messages[0]).toMatchObject({ content: "hello world" });

    const stale = reduceChatStream(delta.state, {
      type: "reconnect-snapshot",
      snapshot: { session_id: "s1", turn_active: true, stream_text: "old", stream_revision: 1 },
    });
    expect(stale.state.messages[0]).toMatchObject({ content: "hello world" });

    const finished = reduceChatStream(delta.state, {
      type: "reconnect-snapshot",
      snapshot: { session_id: "s1", latest_session_id: "s1", turn_active: false },
    });
    expect(finished.state.turnState).toBe("finalizing");
    expect(finished.effects).toContainEqual({ type: "load-history", sessionId: "s1", reason: "snapshot-finalized" });
  });

  it("turns reconnect and bus-gap signals into declarative resync effects", () => {
    const initial = createChatStreamState({ sessionId: "s1" });
    for (const [topic, reason] of [
      ["bus.reconnected", "reconnect"],
      ["bus.gap", "gap"],
      ["bus.stale", "stale"],
      ["bus.wake", "wake"],
    ] as const) {
      const result = reduce(initial, event(topic));
      expect(result.state.needsRecovery).toBe(true);
      expect(result.effects).toContainEqual({ type: "resync", reason, allowIdle: true });
    }
  });
});
