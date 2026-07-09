import { describe, expect, it } from "vitest";
import {
  applySessionRows,
  coalesceSessionRows,
  filterSessionsLocally,
  mergeSessionPage,
  mergeSearchRows,
  mergeSessionRow,
  pendingInitialMessageForSession,
  sessionInfoFromDetail,
} from "./sessionStore";
import type { SessionInfo } from "./api";

function session(overrides: Partial<SessionInfo>): SessionInfo {
  return {
    id: "s1",
    source: "web",
    model: "test",
    title: "Thread",
    started_at: 1,
    ended_at: null,
    last_active: 1,
    is_active: false,
    message_count: 0,
    tool_call_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    preview: null,
    kanban_status: null,
    estimated_cost_usd: null,
    ...overrides,
  };
}

describe("pendingInitialMessageForSession", () => {
  it("returns the optimistic first message for its owning session", () => {
    expect(
      pendingInitialMessageForSession(
        { "thread-a": "Inspect the repo status." },
        "thread-a",
      ),
    ).toBe("Inspect the repo status.");
  });

  it("does not leak an optimistic first message into another selected session", () => {
    expect(
      pendingInitialMessageForSession(
        { "thread-b": "Say hello in one sentence." },
        "thread-a",
      ),
    ).toBeUndefined();
  });

  it("keeps multiple active-thread optimistic messages independently addressable", () => {
    const pending = {
      "thread-a": "Think for a bit and inspect the current repo status.",
      "thread-b": "Say hello in one sentence.",
    };

    expect(pendingInitialMessageForSession(pending, "thread-a")).toBe(
      "Think for a bit and inspect the current repo status.",
    );
    expect(pendingInitialMessageForSession(pending, "thread-b")).toBe(
      "Say hello in one sentence.",
    );
  });

  it("returns nothing when no session is selected", () => {
    expect(
      pendingInitialMessageForSession(
        { "thread-b": "Say hello in one sentence." },
        null,
      ),
    ).toBeUndefined();
  });

  it("merges session rows without replacing useful previews or decreasing counts", () => {
    const merged = mergeSessionRow(
      session({ id: "s1", preview: "useful preview", message_count: 8, is_active: true }),
      session({ id: "s1", preview: "   ", message_count: 4, is_active: false }),
    );

    expect(merged.preview).toBe("useful preview");
    expect(merged.message_count).toBe(8);
    expect(merged.is_active).toBe(false);
  });

  it("coalesces burst rows by session id before applying them", () => {
    const rows = coalesceSessionRows([
      session({ id: "s1", preview: "first", message_count: 1, last_active: 1 }),
      session({ id: "s2", preview: "other", message_count: 1, last_active: 2 }),
      session({ id: "s1", preview: "latest", message_count: 3, last_active: 3 }),
    ]);

    expect(rows.map((row) => [row.id, row.preview, row.message_count])).toEqual([
      ["s1", "latest", 3],
      ["s2", "other", 1],
    ]);
  });

  it("applies coalesced session rows and keeps newest active rows first", () => {
    const prev = [
      session({ id: "older", preview: "old", last_active: 1 }),
      session({ id: "s1", preview: "initial", last_active: 2 }),
    ];

    const next = applySessionRows(prev, [
      session({ id: "s1", preview: "updated", message_count: 5, last_active: 5 }),
      session({ id: "new", preview: "new thread", last_active: 4 }),
    ]);

    expect(next.map((row) => row.id)).toEqual(["s1", "new", "older"]);
    expect(next.find((row) => row.id === "s1")?.preview).toBe("updated");
    expect(next.find((row) => row.id === "s1")?.message_count).toBe(5);
  });

  it("merges overlapping pages deterministically without duplicate sessions", () => {
    const current = [
      session({ id: "newest", last_active: 10 }),
      session({ id: "boundary", last_active: 9, preview: "first page" }),
    ];
    const next = mergeSessionPage(current, [
      session({ id: "boundary", last_active: 9, preview: "second page", message_count: 2 }),
      session({ id: "older", last_active: 8 }),
    ]);

    expect(next.map((row) => row.id)).toEqual(["newest", "boundary", "older"]);
    expect(next.find((row) => row.id === "boundary")?.message_count).toBe(2);
    expect(next.find((row) => row.id === "boundary")?.preview).toBe("second page");
  });

  it("hydrates a complete sidebar row from session detail and FTS metadata", () => {
    const hydrated = sessionInfoFromDetail(
      { id: "old", title: "Old session", message_count: 4 },
      {
        session_id: "old",
        snippet: "matched content",
        role: "user",
        source: "workspace:archive",
        model: "test-model",
        title: "Old session",
        session_started: 12,
      },
    );

    expect(hydrated).toMatchObject({
      id: "old",
      title: "Old session",
      preview: "matched content",
      source: "workspace:archive",
      last_active: 12,
      message_count: 4,
    });
  });

  it("filters loaded session titles and previews synchronously", () => {
    const sessions = [
      session({ id: "title", title: "Release checklist" }),
      session({ id: "preview", title: "Other", preview: "Investigate sidebar latency" }),
      session({ id: "miss", title: "Unrelated" }),
    ];

    expect(filterSessionsLocally(sessions, "SIDEBAR").map((row) => row.id)).toEqual(["preview"]);
    expect(filterSessionsLocally(sessions, "release").map((row) => row.id)).toEqual(["title"]);
  });

  it("combines immediate local and server FTS rows without duplicates", () => {
    const local = [session({ id: "local", last_active: 2 })];
    const server = [
      session({ id: "local", preview: "server duplicate" }),
      session({ id: "history", last_active: 1 }),
    ];

    expect(mergeSearchRows(local, server).map((row) => row.id)).toEqual(["local", "history"]);
  });
});
