import { fetchJSON } from "./apiHelpers";
import type { SkillInfo } from "./apiTypes";

export interface DiscoveredSkill extends SkillInfo {
  scope: "profile" | "external";
  readiness: "available" | "disabled" | "missing_requirements" | "unsupported" | "unknown";
  requirements: { kind: string; name: string; status: "present" | "missing" | "unknown"; optional: boolean }[];
}
export const getSkillIndex = (refresh = false, signal?: AbortSignal) =>
  fetchJSON<DiscoveredSkill[]>(`/api/skills/index?refresh=${refresh}`, { signal });
