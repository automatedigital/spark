import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { beginChildCommand, childCommandKey, childControlSupport, saveChildCommand } from "./subagentControls";
import type { SubagentCapabilities, SubagentRun } from "./apiTypes";
import { setSidebarPreferenceScope } from "./sidebarPrefs";

const capabilities: SubagentCapabilities = {
  schema_version: 1,
  controls: { inspect: { supported: true, reason: null }, interrupt: { supported: true, reason: null }, retry: { supported: true, reason: null } },
  runtime: { available: true, async_enabled: true, worker_kind: "process_local", completion_delivery: "next_explicit_parent_turn" },
};
beforeEach(() => setSidebarPreferenceScope("fixture-profile"));
afterEach(() => { vi.unstubAllGlobals(); setSidebarPreferenceScope("unresolved"); });
describe("child controls", () => {
  it("prefers exact child controls over aggregates and incomplete lists", () => {
    const children = [{ id: "owned", status: "running" }, { id: "unowned", status: "running" }];
    const exact: SubagentCapabilities = {
      ...capabilities,
      controls: { ...capabilities.controls, interrupt: { supported: false, reason: "List is incomplete" } },
      children: {
        owned: { controls: capabilities.controls },
        unowned: { controls: { ...capabilities.controls, interrupt: { supported: false, reason: "No live owned child" } } },
      },
    };
    expect(childControlSupport("interrupt", children[0], children, exact).supported).toBe(true);
    expect(childControlSupport("interrupt", children[0], children.slice(0, 1), exact).supported).toBe(true);
    expect(childControlSupport("interrupt", children[1], children, exact)).toEqual({ supported: false, reason: "No live owned child" });
    expect(childControlSupport("interrupt", { id: "unknown", status: "running" }, children, exact).supported).toBe(false);
  });
  it("waits for profile identity and namespaces receipts by profile", () => {
    const child = { id: "child", status: "running" };
    const key = childCommandKey("parent", "child", "interrupt");
    setSidebarPreferenceScope("unresolved");
    expect(childControlSupport("interrupt", child, [child], capabilities).supported).toBe(false);
    setSidebarPreferenceScope("another-profile");
    expect(childCommandKey("parent", "child", "interrupt")).not.toBe(key);
  });
  it("disables unknown, stale and unsupported controls with explanations", () => {
    const child = { id: "one", status: "running", provider: "custom-provider" };
    expect(childControlSupport("interrupt", child, [child], null)).toMatchObject({ supported: false, reason: expect.stringContaining("unknown or stale") });
    expect(childControlSupport("interrupt", { ...child, status: "stale" }, [child], capabilities).supported).toBe(false);
    expect(childControlSupport("retry", child, [child], { ...capabilities, controls: { ...capabilities.controls, retry: { supported: false, reason: "Disabled on this runtime" } } }).reason).toBe("Disabled on this runtime");
  });
  it("does not turn an any-child capability into per-child ownership", () => {
    const children = [{ id: "a", status: "running" }, { id: "b", status: "running" }];
    expect(childControlSupport("interrupt", children[0], children, capabilities)).toMatchObject({ supported: false, reason: expect.stringContaining("Per-child") });
    expect(childControlSupport("interrupt", children[0], children.slice(0, 1), capabilities).supported).toBe(true);
  });
  it("requires acknowledged async failure for explicit new attempts", () => {
    for (const status of ["uncertain", "stale", "running"]) {
      const child: SubagentRun = { id: status, status, execution_mode: "async" };
      expect(childControlSupport("retry", child, [child], capabilities).supported).toBe(false);
    }
    const child = { id: "failed", status: "failed", execution_mode: "async" };
    expect(childControlSupport("retry", child, [child], capabilities).supported).toBe(true);
    expect(childControlSupport("retry", { ...child, execution_mode: "sync" }, [child], capabilities).supported).toBe(false);
  });
  it("reuses receipt IDs after uncertain responses and isolates children/sessions", () => {
    vi.stubGlobal("sessionStorage", { getItem: () => null, setItem: vi.fn() });
    const key = childCommandKey("parent-a", "child-a", "interrupt");
    const command = beginChildCommand(key);
    expect(beginChildCommand(key).requestId).toBe(command.requestId);
    saveChildCommand(key, { ...command, state: "accepted" });
    expect(beginChildCommand(key).state).toBe("accepted");
    expect(beginChildCommand(childCommandKey("parent-b", "child-a", "interrupt")).requestId).not.toBe(command.requestId);
    expect(beginChildCommand(childCommandKey("parent-a", "child-a", "retry")).requestId).not.toBe(command.requestId);
  });
});
