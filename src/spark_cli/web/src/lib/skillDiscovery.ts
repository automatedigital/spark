import { fetchJSON } from "./apiHelpers";
import type { SkillInfo } from "./apiTypes";

export interface DiscoveredSkill extends SkillInfo {
  scope: "profile" | "external" | "project";
  revision: string;
  removed?: boolean;
  readiness: "available" | "disabled" | "missing_requirements" | "unsupported" | "unknown";
  requirements: { kind: string; name: string; status: "present" | "missing" | "unknown"; optional: boolean }[];
}
export const getSkillIndex = (refresh = false, signal?: AbortSignal, project?: string | null) =>
  fetchJSON<DiscoveredSkill[]>(`/api/skills/index?refresh=${refresh}${project ? `&workspace_slug=${encodeURIComponent(project)}` : ""}`, { signal });
export const getSkillDetail = (id: string, project?: string | null) =>
  fetchJSON<import("./apiTypes").SkillDetail>(`/api/skills/${encodeURIComponent(id)}${project ? `?workspace_slug=${encodeURIComponent(project)}` : ""}`);
