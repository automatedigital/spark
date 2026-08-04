import { describe, expect, it } from "vitest";
import {
  earlierHistoryRequest,
  hasEarlierFromResponse,
  isCurrentSessionResponse,
  prependEarlierMessages,
} from "./chatHistory";
import type { ChatMessage } from "./chatTranscriptMerge";

const user = (id: string, sessionIdx?: number): ChatMessage => ({
  id,
  role: "user",
  content: id,
  ...(sessionIdx == null ? {} : { sessionIdx }),
});

describe("earlier chat history contract", () => {
  it("requests a page with the normalized before_id from the first persisted row", () => {
    expect(earlierHistoryRequest({
      sessionId: "session-a",
      loadingEarlier: false,
      limit: 50,
      messages: [
        { id: "local", role: "user", content: "optimistic" },
        user("db:42", 42),
      ],
    })).toEqual({ sessionId: "session-a", limit: 50, beforeId: "42" });
  });

  it("requests the first page cursor when no persisted row is available", () => {
    expect(earlierHistoryRequest({
      sessionId: "session-a",
      loadingEarlier: false,
      limit: 50,
      messages: [user("local")],
    })).toEqual({ sessionId: "session-a", limit: 50 });
  });

  it("skips a request without a session or while another page is loading", () => {
    const input = { sessionId: "session-a", loadingEarlier: true, limit: 50, messages: [] };
    expect(earlierHistoryRequest(input)).toBeNull();
    expect(earlierHistoryRequest({ ...input, sessionId: null, loadingEarlier: false })).toBeNull();
  });

  it("prepends only unseen rows and preserves the current array when nothing is added", () => {
    const current: ChatMessage[] = [user("db:2", 2), user("db:3", 3)];
    const merged = prependEarlierMessages(
      current,
      [user("db:1", 1), user("db:2", 2), user("db:1", 1)],
    );

    expect(merged.map((message) => message.id)).toEqual(["db:1", "db:2", "db:3"]);
    expect(prependEarlierMessages(current, [user("db:2", 2)])).toBe(current);
  });

  it("preserves the server has_earlier decision and defaults missing values to false", () => {
    expect(hasEarlierFromResponse(false)).toBe(false);
    expect(hasEarlierFromResponse(undefined)).toBe(false);
    expect(hasEarlierFromResponse(null)).toBe(false);
    expect(hasEarlierFromResponse(true)).toBe(true);
  });
});

describe("session response guard", () => {
  it("rejects a response from an older recovery sequence", () => {
    expect(isCurrentSessionResponse(1, 2, "session-a", new Set(), "session-a")).toBe(false);
  });

  it("rejects a response for a different active session", () => {
    expect(isCurrentSessionResponse(2, 2, "session-b", new Set(), "session-a")).toBe(false);
  });

  it("accepts a migrated session alias for the active session", () => {
    expect(isCurrentSessionResponse(
      2,
      2,
      "session-leaf",
      new Set(["session-parent"]),
      "session-parent",
    )).toBe(true);
  });
});
