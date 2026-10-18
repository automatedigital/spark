import type { SubagentNavigation, SubagentWorktreeProject } from "./apiTypes";
import type { GlobalNavTarget } from "./globalNavigation";

export interface ChildNavigationActions {
  current: () => boolean;
  read: () => Promise<SubagentNavigation>;
  openWorktree: () => Promise<SubagentWorktreeProject>;
  refreshProjects: (requiredSlug: string) => Promise<boolean>;
  navigate: (target: GlobalNavTarget) => void;
}

/** Every awaited boundary is fenced by the initiating thread/profile/generation. */
export async function activateChildNavigation(kind: "task" | "worktree", childId: string, actions: ChildNavigationActions) {
  if (!actions.current()) return;
  if (kind === "task") {
    const value = await actions.read();
    if (!actions.current()) return;
    if (value.schema_version !== 1 || value.subagent_id !== childId || !value.task.supported || !value.task.id) {
      throw new Error(value.task.reason || "This child has no verified task destination.");
    }
    actions.navigate({ type: "task", id: value.task.id });
    return;
  }
  const value = await actions.openWorktree();
  if (!actions.current()) return;
  if (!value.ok || value.subagent_id !== childId || !value.project_slug) throw new Error("The worktree project could not be opened.");
  if (!await actions.refreshProjects(value.project_slug)) throw new Error("The worktree project is missing from the refreshed project list. Open worktree again to retry.");
  if (actions.current()) actions.navigate({ type: "project", id: value.project_slug });
}
