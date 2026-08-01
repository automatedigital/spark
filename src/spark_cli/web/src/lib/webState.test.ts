import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionInfo, SessionMessage } from "@/lib/api";
import {
  NormalizedWebState,
  clearUnsettledOrInvalidDetailCache,
  legacySessionSnapshot,
  parseLegacyWebStateEvent,
  parseWebStateEvent,
  persistSettledDetail,
  readSettledDetail,
  schedulePersistSettledDetail,
  sequenceDecision,
  type WebStateEventV1,
} from "@/lib/webState";

const event = (sequence: number, overrides: Partial<WebStateEventV1> = {}): WebStateEventV1 => ({
  schema_version: 1,
  topic: "sessions.changed",
  entity_id: "s1",
  session_id: "s1",
  sequence,
  projection_version: 1,
  timestamp: 1,
  payload: {},
  data: {},
  server_epoch: "epoch",
  ...overrides,
});

const shell = (id: string, count = 0): SessionInfo => ({
  id,
  source: "web",
  model: null,
  title: id,
  started_at: 1,
  ended_at: null,
  last_active: 1,
  is_active: false,
  message_count: count,
  tool_call_count: 0,
  input_tokens: 0,
  output_tokens: 0,
  preview: null,
  kanban_status: null,
  estimated_cost_usd: null,
});

describe("web state v1 contract", () => {
  it("runtime-validates the versioned envelope", () => {
    expect(parseWebStateEvent(event(1))?.data).toEqual({});
    expect(parseWebStateEvent({ ...event(1), schema_version: 2 })).toBeNull();
    expect(parseWebStateEvent({ ...event(1), sequence: 0 })).toBeNull();
    expect(parseWebStateEvent({ ...event(1), payload: [] })).toBeNull();
  });

  it("detects duplicate, out-of-order, missing, restart and version events", () => {
    const cursor = { sequence: 4, projectionVersion: 1, serverEpoch: "epoch" };
    expect(sequenceDecision(event(4), cursor)).toBe("duplicate");
    expect(sequenceDecision(event(3), cursor)).toBe("duplicate");
    expect(sequenceDecision(event(5), cursor)).toBe("apply");
    expect(sequenceDecision(event(6), cursor)).toBe("gap");
    expect(sequenceDecision(event(5, { server_epoch: "restart" }), cursor)).toBe("snapshot");
    expect(sequenceDecision(event(5, { projection_version: 2 as 1 }), cursor)).toBe("snapshot");
  });

  it("accepts a coalesced event that covers every sequence after the cursor", () => {
    const cursor = { sequence: 4, projectionVersion: 1, serverEpoch: "epoch" };
    expect(sequenceDecision(event(6, { sequence_start: 5 }), cursor)).toBe("apply");
    expect(parseWebStateEvent(event(6, { sequence_start: 7 }))).toBeNull();
  });

  it("normalizes compatibility-release snapshots and SSE without losing shells", () => {
    const snapshot = legacySessionSnapshot(
      { sessions: [shell("s1")], total: 1, limit: 50, offset: 0 },
      "legacy:1",
    );
    expect(snapshot.shells.map((row) => row.id)).toEqual(["s1"]);
    const legacy = parseLegacyWebStateEvent(
      { topic: "sessions.changed", session_id: "s2", ts: 2, data: { action: "created" } },
      { sequence: 7, serverEpoch: "legacy:1" },
    );
    expect(legacy).toMatchObject({ sequence: 8, entity_id: "s2", server_epoch: "legacy:1" });
    expect(parseLegacyWebStateEvent(
      { topic: "sessions.changed", data: [] },
      { sequence: 0, serverEpoch: "legacy" },
    )).toBeNull();
  });
});

describe("normalized shell/detail projections", () => {
  it("keeps selectors referentially stable for unchanged entities", () => {
    const state = new NormalizedWebState();
    const first = state.upsertShell(shell("s1"));
    const same = state.upsertShell(shell("s1"));
    const order = state.replaceShells([shell("s1"), shell("s2")]);
    const sameOrder = state.replaceShells([shell("s1"), shell("s2")]);
    expect(same).toBe(first);
    expect(sameOrder).toBe(order);
    expect(state.selectShell("s1")).toBe(first);
  });

  it("does not keep unselected long chat bodies past their idle TTL", () => {
    const state = new NormalizedWebState();
    const longBody: SessionMessage[] = Array.from({ length: 5_000 }, (_, id) => ({
      id: String(id), role: "assistant", content: "x".repeat(100),
    }));
    state.setDetail({
      sessionId: "old", messages: longBody, status: "idle", mountedAt: 0,
      lastAccessedAt: 0, settled: true,
    });
    state.setDetail({
      sessionId: "selected", messages: longBody, status: "streaming", mountedAt: 0,
      lastAccessedAt: 0, settled: false,
    });
    expect(state.expireIdleDetails("selected", 120_001)).toEqual(["old"]);
    expect(state.details.has("old")).toBe(false);
    expect(state.details.has("selected")).toBe(true);
  });
});

describe("settled-only detail persistence", () => {
  const values = new Map<string, string>();
  beforeEach(() => {
    values.clear();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
      clear: () => values.clear(),
    });
  });

  it("never serializes active token/tool payloads and restores settled detail", () => {
    const messages: SessionMessage[] = [{ id: "1", role: "assistant", content: "done" }];
    expect(persistSettledDetail("s1", messages, 4, false)).toBe(false);
    expect(readSettledDetail("s1")).toBeNull();
    expect(persistSettledDetail("s1", messages, 5, true)).toBe(true);
    expect(readSettledDetail("s1")?.sequence).toBe(5);
  });

  it("cleans malformed crash remnants", () => {
    localStorage.setItem("spark-web-state-settled-v1", "not-json");
    clearUnsettledOrInvalidDetailCache();
    expect(readSettledDetail("s1")).toBeNull();
  });

  it("debounces repeated settled projections to the latest payload", () => {
    vi.useFakeTimers();
    const first: SessionMessage[] = [{ role: "assistant", content: "first" }];
    const final: SessionMessage[] = [{ role: "assistant", content: "final" }];
    schedulePersistSettledDetail("s1", first, 1, true, 50);
    schedulePersistSettledDetail("s1", final, 2, true, 50);
    expect(readSettledDetail("s1")).toBeNull();
    vi.advanceTimersByTime(50);
    expect(readSettledDetail("s1")?.messages[0].content).toBe("final");
    vi.useRealTimers();
  });
});
