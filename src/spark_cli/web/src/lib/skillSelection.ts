import { draftKey, flushDraft, getDraft, updateDraft } from "./draftStore";
import type { DraftScope } from "./draftStore";
import type { DiscoveredSkill } from "./skillDiscovery";

const targets = new Map<string, DraftScope>();
/** Composer registers confirmed identities only; selecting never sends a message. */
export function registerSkillTarget(key: string): void {
  try {
    const [backend, profile, project, thread] = JSON.parse(key.slice(key.indexOf(":") + 1));
    if (typeof backend !== "string" || typeof profile !== "string" || profile === "pending-identity" || !thread) return;
    targets.set(key, { backend, profile, project, thread });
    if (targets.size > 40) targets.delete(targets.keys().next().value!);
  } catch { /* Unconfirmed/corrupt identity cannot become a target. */ }
}
export function skillTargets(backend: string, profile: string): DraftScope[] {
  return [...targets.values()].filter((scope) => scope.backend === backend && scope.profile === profile);
}
export function stageSkill(scope: DraftScope, skill: DiscoveredSkill): void {
  const key = draftKey(scope);
  if (!targets.has(key) || !scope.thread || !skill.revision || skill.removed) throw new Error("Open the intended thread before selecting a skill.");
  const entry = getDraft(key);
  if (entry.status === "conflict") throw new Error("Resolve the thread's draft conflict first.");
  const item = {
    id: `skill:${skill.skill_id}`, type: "skill" as const, skill_id: skill.skill_id,
    skill_revision: skill.revision, skill_profile: scope.profile, skill_thread: scope.thread,
    skill_project: scope.project ?? null, inclusion_mode: "full" as const,
    scope: "one_turn" as const, size_bytes: 0, label: `Skill: ${skill.name}`,
  };
  updateDraft(key, { contextItems: [...entry.draft.contextItems.filter((item) => item.id !== `skill:${skill.skill_id}`), item] });
  flushDraft(key);
}
