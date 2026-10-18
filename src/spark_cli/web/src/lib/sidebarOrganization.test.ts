import { describe, expect, it } from "vitest";
import type { SessionInfo } from "./apiTypes";
import { DEFAULT_SIDEBAR_METADATA as defaults } from "./api_sidebar";
import { isEffectivelySettled, mergeSidebarEntries, orderSidebarSessions, sidebarMovePatches, sidebarStatus } from "./sidebarOrganization";

const session = (id: string, started_at = 1, last_active = started_at) => ({ id, started_at, last_active, is_active: false } as SessionInfo);

describe("durable sidebar organization", () => {
  it("keeps activity ordering until a user arranges rows; streaming cannot reshuffle manual rows", () => {
    const rows = [session("a", 1, 100), session("b", 2, 200), session("c", 3, 300)];
    expect(orderSidebarSessions(rows, {}).map((s) => s.id)).toEqual(["c", "b", "a"]);
    const entries = { a: { ...defaults, position: 1 }, b: { ...defaults, position: 2 } };
    expect(orderSidebarSessions(rows, entries).map((s) => s.id)).toEqual(["a", "b", "c"]);
    rows[1].last_active = 1e12;
    expect(orderSidebarSessions(rows, entries).map((s) => s.id)).toEqual(["a", "b", "c"]);
  });
  it("freezes existing activity order when moving with keyboard and preserves every other metadata field", () => {
    const rows = [session("a", 1, 500), session("b", 2, 400), session("c", 3, 300)];
    const entries = { a: { ...defaults, pinned: true, revision: 2 } };
    const patches = sidebarMovePatches(rows, entries, "c", -1);
    const next = Object.fromEntries(patches.map((p) => [p.id, { ...defaults, ...entries[p.id as "a"], position: p.position }]));
    expect(orderSidebarSessions(rows, next).map((s) => s.id)).toEqual(["a", "c", "b"]);
    expect(next.a.pinned).toBe(true);
    expect(patches.find((p) => p.id === "a")?.revision).toBe(2);
    expect(sidebarMovePatches(rows, entries, "a", -1)).toEqual([]);
    expect(sidebarMovePatches(rows, entries, "c", 1)).toEqual([]);
  });
  it("uses one CAS for a move after positions are assigned", () => {
    const rows = [session("a"), session("b"), session("c")];
    const entries = { a: { ...defaults, position: 0 }, b: { ...defaults, position: 1024 }, c: { ...defaults, position: 2048, revision: 9 } };
    expect(sidebarMovePatches(rows, entries, "c", -1)).toEqual([{ id: "c", revision: 9, position: 512 }]);
  });
  it("a stale snapshot cannot undo a newer accepted mutation", () => {
    const current = { a: { ...defaults, pinned: true, revision: 3 } };
    expect(mergeSidebarEntries(current, { a: { ...defaults, revision: 2 } }).a).toEqual(current.a);
    expect(mergeSidebarEntries(current, {})).toEqual({});
  });
  it("keeps pending decisions and renewed work visible even if metadata says settled", () => {
    const row = session("a");
    const entries = { a: { ...defaults, settled: true } };
    expect(isEffectivelySettled(row, entries)).toBe(true);
    const attention = { pending_decision: true, running: false, status: "completed" };
    expect(isEffectivelySettled(row, entries, attention)).toBe(false);
    expect(sidebarStatus(row, attention)).toBe("Needs you");
    expect(isEffectivelySettled({ ...row, is_active: true }, entries)).toBe(false);
    expect(sidebarStatus(row, { ...attention, running: true })).toBe("Needs you");
    expect(sidebarStatus(row, { ...attention, pending_decision: false, status: "failed" })).toBe("Failed");
  });
  it("scales ordering and status projection over 1,000 mixed rows", () => {
    const rows = Array.from({ length: 1000 }, (_, index) => session(`thread-${index}`, index));
    const entries = Object.fromEntries(rows.map((row, index) => [row.id, { ...defaults, position: index, settled: index % 3 === 0, pinned: index % 10 === 0 }]));
    expect(orderSidebarSessions(rows.reverse(), entries)[0].id).toBe("thread-0");
    expect(rows.filter((row) => isEffectivelySettled(row, entries))).toHaveLength(334);
  });
});
