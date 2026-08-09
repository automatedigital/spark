/** skill endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  SkillDetail,
  SkillInfo,
  SkillsAnalyticsResponse,
} from "./apiTypes";

export const skillApi = {
  getSkillsAnalytics: (limit = 20) =>
    fetchJSON<SkillsAnalyticsResponse>(`/api/analytics/skills?limit=${limit}`),
  getSkills: () => fetchJSON<SkillInfo[]>("/api/skills"),
  getSkill: (skillId: string) =>
    fetchJSON<SkillDetail>(`/api/skills/${encodeURIComponent(skillId)}`),
  saveSkill: (skillId: string, content: string) =>
    fetchJSON<{ ok: boolean; skill: SkillDetail }>(`/api/skills/${encodeURIComponent(skillId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  deleteSkill: (skillId: string) =>
    fetchJSON<{ ok: boolean; name: string }>(`/api/skills/${encodeURIComponent(skillId)}`, {
      method: "DELETE",
    }),
  restoreSkill: (skillId: string) =>
    fetchJSON<{ ok: boolean; skill: SkillDetail }>(`/api/skills/${encodeURIComponent(skillId)}/restore`, {
      method: "POST",
    }),
  toggleSkill: (name: string, enabled: boolean, skillId?: string) =>
    fetchJSON<{ ok: boolean }>("/api/skills/toggle", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, enabled, ...(skillId ? { skill_id: skillId } : {}) }),
    }),
  setupOnboardingSkills: (mode: "recommended" | "minimal" | "none") =>
    fetchJSON<{ ok: boolean; mode: string; seeded: number; total_bundled: number }>(
      "/api/onboarding/skills",
      { method: "POST", body: JSON.stringify({ mode }), headers: { "Content-Type": "application/json" } },
    ),
  enableConnectorSkills: (connectorId: string) =>
    fetchJSON<{ ok?: boolean; skills?: string[]; toolsets?: string[]; error?: string }>(
      `/api/connectors/${encodeURIComponent(connectorId)}/skills/enable`,
      { method: "POST" },
    ),
};
