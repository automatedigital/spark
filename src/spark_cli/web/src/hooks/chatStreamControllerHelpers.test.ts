import { describe, expect, it, vi } from "vitest";
import {
  eventAction,
  executeChatStreamEffect,
  flushAction,
  isCurrentChatStreamEffect,
  reduceChatStreamController,
  snapshotAction,
  type ChatStreamControllerCallbacks,
  type QueuedChatStreamEffect,
} from "./chatStreamControllerHelpers";
import { createChatStreamState, type ChatStreamEvent } from "@/lib/chatStreamReducer";

function event(
  topic: string,
  data: Record<string, unknown> = {},
  sessionId = "s1",
  sequence?: number,
): ChatStreamEvent {
  return { topic, data, session_id: sessionId, ...(sequence === undefined ? {} : { sequence }) };
}

describe("chat stream controller helpers", () => {
  it("reduces event, snapshot, and flush actions through the pure reducer", () => {
    const initial = createChatStreamState({ sessionId: "s1" });
    const eventTransition = reduceChatStreamController(initial, eventAction(event("chat.token", { t: "hello" })));
    const flushed = reduceChatStreamController(eventTransition.state, flushAction("manual"));
    const snapshot = reduceChatStreamController(flushed.state, snapshotAction({
      session_id: "s1",
      active_turn_session_id: "s1",
      turn_active: true,
      stream_text: "hello world",
      stream_revision: 2,
      stream_text_chars: 11,
    }));

    expect(eventTransition.state.tokenBuffer).toBe("hello");
    expect(flushed.state.messages[0]).toMatchObject({ role: "assistant", content: "hello" });
    expect(snapshot.accepted).toBe(true);
    expect(snapshot.state.messages[0]).toMatchObject({ content: "hello world" });
  });

  it("captures effect session and recovery guards at transition time", () => {
    const initial = createChatStreamState({ sessionId: "old", recoverySequence: 7 });
    const transition = reduceChatStreamController(initial, eventAction(event("chat.turn_done", {
      final_assistant_present: true,
    }, "old", 3)));
    const [history, flush] = transition.queuedEffects;

    expect(history).toMatchObject({
      effect: { type: "load-history", sessionId: "old", reason: "turn-done" },
      sessionId: "old",
      recoverySequence: 7,
    });
    expect(flush).toMatchObject({
      effect: { type: "flush-stream", reason: "turn-done" },
      sessionId: "old",
      recoverySequence: 7,
    });
  });

  it("accepts effects for migrated aliases but rejects effects after a recovery reset", () => {
    const migrated = createChatStreamState({
      sessionId: "new",
      aliases: ["old"],
      recoverySequence: 4,
    });
    const queued: QueuedChatStreamEffect = {
      effect: { type: "load-history", sessionId: "old", reason: "failure" },
      sessionId: "old",
      recoverySequence: 4,
    };

    expect(isCurrentChatStreamEffect(queued, migrated)).toBe(true);
    expect(isCurrentChatStreamEffect(queued, {
      ...migrated,
      recoverySequence: 5,
    })).toBe(false);
    expect(isCurrentChatStreamEffect(queued, {
      ...migrated,
      activeSessionId: "other",
      sessionAliases: ["other"],
    })).toBe(false);
  });

  it("maps each declarative effect to its controller callback without doing I/O", async () => {
    const callbacks: ChatStreamControllerCallbacks = {
      onFlushStream: vi.fn(),
      onResync: vi.fn(),
      onLoadHistory: vi.fn(async () => {}),
    };
    const context = { sessionId: "s1", recoverySequence: 2 };

    executeChatStreamEffect({
      ...context,
      effect: { type: "flush-stream", reason: "approval" },
    }, callbacks);
    executeChatStreamEffect({
      ...context,
      effect: { type: "resync", reason: "gap", allowIdle: true },
    }, callbacks);
    await executeChatStreamEffect({
      ...context,
      effect: { type: "load-history", sessionId: "alias", reason: "failure" },
    }, callbacks);

    expect(callbacks.onFlushStream).toHaveBeenCalledWith("approval");
    expect(callbacks.onResync).toHaveBeenCalledWith({
      reason: "gap",
      allowIdle: true,
      sessionId: "s1",
      recoverySequence: 2,
    });
    expect(callbacks.onLoadHistory).toHaveBeenCalledWith({
      sessionId: "alias",
      reason: "failure",
      recoverySequence: 2,
    });
  });

  it("preserves the reducer's duplicate, ordering, and foreign-session guards", () => {
    const initial = createChatStreamState({ sessionId: "s1" });
    const accepted = reduceChatStreamController(initial, eventAction(event("chat.token", { t: "ok" }, "s1", 4)));
    const duplicate = reduceChatStreamController(accepted.state, eventAction(event("chat.token", { t: "bad" }, "s1", 4)));
    const foreign = reduceChatStreamController(accepted.state, eventAction(event("chat.token", { t: "bad" }, "s2", 5)));

    expect(accepted.accepted).toBe(true);
    expect(duplicate.accepted).toBe(false);
    expect(foreign.accepted).toBe(false);
    expect(duplicate.state.tokenBuffer).toBe("ok");
    expect(foreign.state.tokenBuffer).toBe("ok");
  });
});
