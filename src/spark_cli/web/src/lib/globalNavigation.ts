export type GlobalNavTarget =
  | { type: "project"; id: string }
  | { type: "thread"; id: string }
  | { type: "task"; id: string }
  | { type: "scheduled-task"; id: string }
  | { type: "skill"; id: string }
  | { type: "file"; path: string; name?: string }
  // Canvas: `id` is the canvas id; `scope`/`slug` locate it (global vs a project).
  | { type: "canvas"; id: string; scope: "global" | "project"; slug?: string | null };

export const GLOBAL_NAV_TARGET_KEY = "spark-global-nav-target";
export const GLOBAL_NAV_EVENT = "spark-global-nav";
type GlobalNavTargetFor<T extends GlobalNavTarget["type"]> = Extract<GlobalNavTarget, { type: T }>;

export function setGlobalNavTarget(target: GlobalNavTarget): void {
  localStorage.setItem(GLOBAL_NAV_TARGET_KEY, JSON.stringify(target));
  window.dispatchEvent(new CustomEvent<GlobalNavTarget>(GLOBAL_NAV_EVENT, { detail: target }));
}

export function takeGlobalNavTarget<T extends GlobalNavTarget["type"]>(type: T): GlobalNavTargetFor<T> | null {
  try {
    const raw = localStorage.getItem(GLOBAL_NAV_TARGET_KEY);
    if (!raw) return null;
    const target = JSON.parse(raw) as GlobalNavTarget;
    if (target.type !== type) return null;
    localStorage.removeItem(GLOBAL_NAV_TARGET_KEY);
    return target as GlobalNavTargetFor<T>;
  } catch {
    localStorage.removeItem(GLOBAL_NAV_TARGET_KEY);
    return null;
  }
}
