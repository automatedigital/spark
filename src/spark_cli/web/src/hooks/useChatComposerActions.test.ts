import { describe, expect, it, vi } from "vitest";
import type { ContextItem } from "@/lib/context";
import { createComposerState, planSend, planStop } from "@/lib/chatComposerController";
import {
  applyComposerPlanIntents,
  executeComposerEffect,
  type ComposerApi,
} from "./useChatComposerActions";

const contextItem: ContextItem = {
  id: "context-1",
  type: "file",
  source_path: "/tmp/context.txt",
  inclusion_mode: "path_only",
  scope: "one_turn",
  size_bytes: 1,
};

function fakeApi() {
  return {
    postConversation: vi.fn(async () => ({ session_id: "new-session", ok: true })),
    postConversationMessage: vi.fn(async () => ({ session_id: "existing-session", ok: true })),
    startWorkspaceConversation: vi.fn(async () => ({ session_id: "workspace-session", ok: true, source: "workspace" })),
    interruptConversation: vi.fn(async () => ({ ok: true })),
  } satisfies ComposerApi;
}

describe("useChatComposerActions helpers", () => {
  it("executes each planned transport effect through one runner", async () => {
    const api = fakeApi();
    const retry = vi.fn(async () => undefined);
    const fork = vi.fn(async () => undefined);
    const runner = { apiClient: api, retry, fork };

    await executeComposerEffect({
      type: "start-conversation", message: "hello", contextItems: [contextItem],
    }, runner);
    await executeComposerEffect({
      type: "start-workspace-conversation", workspaceSlug: "project-a", message: "build", contextItems: [],
    }, runner);
    await executeComposerEffect({
      type: "post-conversation-message", sessionId: "session-1", message: "follow up", contextItems: [],
    }, runner);
    await executeComposerEffect({
      type: "interrupt-conversation", sessionId: "session-1", message: "redirect",
    }, runner);
    await executeComposerEffect({
      type: "retry-conversation", sessionId: "session-1", messageIndex: 4, message: "edited",
    }, runner);
    await executeComposerEffect({
      type: "fork-conversation", sessionId: "session-1", fromMessageIndex: 4,
    }, runner);

    expect(api.postConversation).toHaveBeenCalledWith("hello", undefined, [contextItem]);
    expect(api.startWorkspaceConversation).toHaveBeenCalledWith("project-a", "build", undefined, []);
    expect(api.postConversationMessage).toHaveBeenCalledWith("session-1", "follow up", []);
    expect(api.interruptConversation).toHaveBeenCalledWith("session-1", "redirect");
    expect(retry).toHaveBeenCalledWith(4, "edited");
    expect(fork).toHaveBeenCalledWith(4);
  });

  it("applies controller intents without recreating composer state", () => {
    const state = createComposerState({ contextItems: [contextItem] });
    const plan = planSend(state, { messageId: "message-1", text: " hello " });
    const rows: unknown[] = [];
    let nextTurn = state.turnState;
    let nextStatus = state.statusLabel;
    let retained: ContextItem[] = [];
    let edit: { index: number; text: string } | null = null;

    applyComposerPlanIntents(plan, {
      setTurnState: (value) => { nextTurn = value; },
      setStatusLabel: (value) => { nextStatus = value; },
      appendUserRow: (row) => { rows.push(row); },
      retainContext: (items) => { retained = items; },
      openEdit: (index, text) => { edit = { index, text }; },
    });

    expect(nextTurn).toBe("starting");
    expect(nextStatus).toBe("Loading LLM response");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ role: "user", content: "hello" });
    expect(retained).toEqual([]);
    expect(edit).toBeNull();
  });

  it("keeps interrupt effects side-effect-only after applying their transition", () => {
    const state = createComposerState({ sessionId: "session-1", turnState: "streaming" });
    const plan = planStop(state);
    const statuses: Array<string | null> = [];
    applyComposerPlanIntents(plan, {
      setTurnState: () => {},
      setStatusLabel: (value) => { statuses.push(value); },
      appendUserRow: () => {},
      retainContext: () => {},
      openEdit: () => {},
    });
    expect(statuses).toEqual(["Stopping…"]);
  });
});
