import { afterEach, describe, expect, it } from "vitest";
import {
  currentTurnLiveAssistantIndex,
  LOCAL_CACHE_TEXT_CHARS,
  localTurnCache,
  mergeSyncedMessages,
  rememberLocalTurn,
  type ChatMessage,
} from "./chatTranscriptMerge";

describe("currentTurnLiveAssistantIndex", () => {
  it("never reuses an assistant from before the latest user message", () => {
    const messages: ChatMessage[] = [
      { id: "a-old", role: "assistant", content: "previous answer" },
      { id: "u-new", role: "user", content: "new question" },
    ];

    expect(currentTurnLiveAssistantIndex(messages)).toBe(-1);
  });

  it("finds the current live assistant across reasoning and tool rows", () => {
    const messages: ChatMessage[] = [
      { id: "u-new", role: "user", content: "new question" },
      { id: "r", role: "reasoning", text: "thinking" },
      { id: "a-live", role: "assistant", content: "partial", streaming: true },
      { id: "t", role: "tool", toolId: "1", name: "lookup", args: {} },
    ];

    expect(currentTurnLiveAssistantIndex(messages)).toBe(2);
  });
});

afterEach(() => {
  localTurnCache.clear();
});

describe("chat transcript merge", () => {
  it("bounds large completed responses and reasoning in the local recovery cache", () => {
    rememberLocalTurn("large", [
      { id: "a", role: "assistant", content: "a".repeat(LOCAL_CACHE_TEXT_CHARS * 2) },
      { id: "r", role: "reasoning", text: "r".repeat(LOCAL_CACHE_TEXT_CHARS * 2) },
    ]);
    const cached = localTurnCache.get("large") ?? [];
    expect((cached[0] as Extract<ChatMessage, { role: "assistant" }>).content).toHaveLength(LOCAL_CACHE_TEXT_CHARS);
    expect((cached[1] as Extract<ChatMessage, { role: "reasoning" }>).text).toHaveLength(LOCAL_CACHE_TEXT_CHARS);
  });

  it("trusts saved assistant rows after a completed turn instead of keeping duplicated local rows", () => {
    const sessionId = "session-dup";
    const saved: ChatMessage[] = [
      { id: "db:1", role: "user", content: "Tell me a turtle story" },
      { id: "db:2", role: "assistant", content: "Pip found a lucky stone." },
      { id: "db:3", role: "user", content: "Make it child-friendly" },
      { id: "db:4", role: "assistant", content: "Pip gave the happy frog his stone back." },
    ];
    const duplicatedLocal: ChatMessage[] = [
      ...saved,
      {
        id: "local-duplicate",
        role: "assistant",
        content: "Pip gave the happy frog his stone back. Pip smiled.",
        streaming: false,
      },
      { id: "feedback", role: "feedback_form" },
    ];
    localTurnCache.set(sessionId, duplicatedLocal);

    const merged = mergeSyncedMessages(saved, duplicatedLocal, sessionId, {
      preferSyncedAssistants: true,
    });

    expect(merged.filter((m) => m.role === "assistant").map((m) => m.content)).toEqual([
      "Pip found a lucky stone.",
      "Pip gave the happy frog his stone back.",
    ]);
    expect(merged.at(-1)).toEqual({ id: "feedback", role: "feedback_form" });
  });

  it("replaces a bounded live tail with the exact saved final response", () => {
    const sessionId = "session-windowed-final";
    const finalContent = Array.from({ length: 20_000 }, (_, index) => `line-${index}\n`).join("");
    const tail = finalContent.slice(-65_536);
    const live: ChatMessage[] = [{
      id: "local-live",
      role: "assistant",
      content: tail,
      streaming: false,
      liveTotalChars: finalContent.length,
      liveOmittedChars: finalContent.length - tail.length,
      liveFenceCount: 0,
    }];
    const saved: ChatMessage[] = [{ id: "db:final", role: "assistant", content: finalContent }];

    const merged = mergeSyncedMessages(saved, live, sessionId, {
      preferSyncedAssistants: true,
      syncedComplete: true,
    });

    expect(merged).toEqual(saved);
    expect((merged[0] as Extract<ChatMessage, { role: "assistant" }>).content.length).toBe(finalContent.length);
  });

  it("still keeps cached assistant progress while the saved transcript is behind", () => {
    const sessionId = "session-streaming";
    const saved: ChatMessage[] = [
      { id: "db:1", role: "user", content: "Tell me a turtle story" },
    ];
    localTurnCache.set(sessionId, [
      ...saved,
      { id: "local-a1", role: "assistant", content: "Once there was a turtle", streaming: true },
    ]);

    const merged = mergeSyncedMessages(saved, [], sessionId);

    expect(merged).toEqual([
      ...saved,
      { id: "local-a1", role: "assistant", content: "Once there was a turtle", streaming: false },
    ]);
  });

  it("does not replace richer local history with an incomplete synced tail page", () => {
    const sessionId = "session-tail";
    const tailPage: ChatMessage[] = [
      { id: "db:10", role: "user", content: "Latest question" },
      { id: "db:11", role: "assistant", content: "Latest answer" },
    ];
    const localHistory: ChatMessage[] = [
      { id: "db:1", role: "user", content: "Older question" },
      { id: "db:2", role: "assistant", content: "Older answer" },
      ...tailPage,
    ];

    const merged = mergeSyncedMessages(tailPage, localHistory, sessionId, {
      preferSyncedAssistants: true,
      syncedComplete: false,
    });

    expect(merged.filter((m) => m.role === "assistant").map((m) => m.content)).toEqual([
      "Older answer",
      "Latest answer",
    ]);
  });

  it("does not append a cached streamed assistant when saved history has the final answer", () => {
    const sessionId = "session-local-prefix-dup";
    const saved: ChatMessage[] = [
      { id: "db:1", role: "user", content: "Status?" },
      { id: "db:2", role: "assistant", content: "The deployment is still running." },
    ];
    const cached: ChatMessage[] = [
      ...saved,
      {
        id: "local-stream",
        role: "assistant",
        content: "The deployment is still running. I will keep watching it.",
        streaming: true,
      },
    ];
    localTurnCache.set(sessionId, cached);

    const merged = mergeSyncedMessages(saved, cached, sessionId);

    expect(merged.filter((m) => m.role === "assistant").map((m) => m.content)).toEqual([
      "The deployment is still running.",
    ]);
  });

  it("keeps richer live assistant progress when saved history is only a checkpoint prefix", () => {
    const sessionId = "session-active-checkpoint";
    const saved: ChatMessage[] = [
      { id: "db:1", role: "user", content: "Stream status?" },
      { id: "db:2", role: "assistant", content: "alpha chunk 1. " },
    ];
    const live: ChatMessage[] = [
      { id: "db:1", role: "user", content: "Stream status?" },
      { id: "local-live", role: "assistant", content: "alpha chunk 1. alpha chunk 2. ", streaming: true, renderRevision: 2 },
    ];

    const merged = mergeSyncedMessages(saved, live, sessionId, {
      preserveLocalAssistantPrefix: true,
    });

    expect(merged.filter((m) => m.role === "assistant")).toEqual([
      {
        id: "db:2",
        role: "assistant",
        content: "alpha chunk 1. alpha chunk 2. ",
        streaming: true,
        renderRevision: 2,
      },
    ]);
  });
});
