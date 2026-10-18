import { describe, expect, it, vi } from "vitest";
import { activateChildNavigation, type ChildNavigationActions } from "./subagentNavigation";

function fixture() {
  const actions: ChildNavigationActions = {
    current: vi.fn(() => true),
    read: vi.fn(async () => ({ schema_version: 1, subagent_id: "child", task: { supported: true, reason: null, id: "actual-task", run_id: 12 }, worktree: { supported: true, reason: null } })),
    openWorktree: vi.fn(async () => ({ ok: true, subagent_id: "child", project_slug: "actual-checkout" })),
    refreshProjects: vi.fn(async () => true),
    navigate: vi.fn(),
  };
  return actions;
}

describe("child navigation", () => {
  it("uses a freshly verified real task ID without opening a worktree", async () => {
    const actions = fixture();
    await activateChildNavigation("task", "child", actions);
    expect(actions.navigate).toHaveBeenCalledWith({ type: "task", id: "actual-task" });
    expect(actions.openWorktree).not.toHaveBeenCalled();
  });
  it("publishes projects before navigating to the actual checkout", async () => {
    const actions = fixture();
    await activateChildNavigation("worktree", "child", actions);
    expect(actions.navigate).toHaveBeenCalledWith({ type: "project", id: "actual-checkout" });
    expect(actions.refreshProjects).toHaveBeenCalledWith("actual-checkout");
    expect(vi.mocked(actions.openWorktree).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(actions.refreshProjects).mock.invocationCallOrder[0]);
    expect(vi.mocked(actions.refreshProjects).mock.invocationCallOrder[0]).toBeLessThan(vi.mocked(actions.navigate).mock.invocationCallOrder[0]);
  });
  it("does not navigate when the task was deleted or belongs to another child", async () => {
    const actions = fixture();
    vi.mocked(actions.read).mockResolvedValueOnce({ schema_version: 1, subagent_id: "child", task: { supported: false, reason: "No linked task in this profile" }, worktree: { supported: false, reason: "Missing checkout" } });
    await expect(activateChildNavigation("task", "child", actions)).rejects.toThrow("No linked task");
    const value = await actions.read();
    vi.mocked(actions.read).mockResolvedValueOnce({ ...value, subagent_id: "other-child" });
    await expect(activateChildNavigation("task", "child", actions)).rejects.toThrow();
    expect(actions.navigate).not.toHaveBeenCalled();
  });
  it.each(["task", "worktree"] as const)("fences late %s acknowledgement after selection/profile change", async (kind) => {
    const actions = fixture();
    let current = true;
    actions.current = () => current;
    if (kind === "task") vi.mocked(actions.read).mockImplementationOnce(async () => { current = false; return { schema_version: 1, subagent_id: "child", task: { supported: true, reason: null, id: "actual-task" }, worktree: { supported: false, reason: null } }; });
    else vi.mocked(actions.openWorktree).mockImplementationOnce(async () => { current = false; return { ok: true, subagent_id: "child", project_slug: "actual-checkout" }; });
    await activateChildNavigation(kind, "child", actions);
    expect(actions.navigate).not.toHaveBeenCalled();
    expect(actions.refreshProjects).not.toHaveBeenCalled();
  });
  it("fences a profile switch while project refresh is pending", async () => {
    const actions = fixture();
    let current = true;
    actions.current = () => current;
    vi.mocked(actions.refreshProjects).mockImplementationOnce(async () => { current = false; return true; });
    await activateChildNavigation("worktree", "child", actions);
    expect(actions.navigate).not.toHaveBeenCalled();
  });
  it("requires a successful project refresh and never auto retries a mutation", async () => {
    const actions = fixture();
    vi.mocked(actions.refreshProjects).mockResolvedValueOnce(false);
    await expect(activateChildNavigation("worktree", "child", actions)).rejects.toThrow("project list");
    expect(actions.openWorktree).toHaveBeenCalledTimes(1);
    expect(actions.navigate).not.toHaveBeenCalled();
  });
});
