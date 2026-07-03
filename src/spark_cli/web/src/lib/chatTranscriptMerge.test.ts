import { afterEach, describe, expect, it } from "vitest";
import {
  localTurnCache,
  mergeSyncedMessages,
  type ChatMessage,
} from "./chatTranscriptMerge";

afterEach(() => {
  localTurnCache.clear();
});

describe("chat transcript merge", () => {
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
});
