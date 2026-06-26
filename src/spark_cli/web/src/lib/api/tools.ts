import type { SkillInfo, SlashCommand, ToolsetInfo } from "../api";
import type { FetchJSON } from "./model";

export function createToolsApi(fetchJSON: FetchJSON) {
  return {
    getSkills: () => fetchJSON<SkillInfo[]>("/api/skills"),
    toggleSkill: (name: string, enabled: boolean) =>
      fetchJSON<{ ok: boolean }>("/api/skills/toggle", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, enabled }),
      }),
    getToolsets: () => fetchJSON<ToolsetInfo[]>("/api/tools/toolsets"),
    getCommands: () => fetchJSON<SlashCommand[]>("/api/commands"),
    setupOnboardingSkills: (mode: "recommended" | "minimal" | "none") =>
      fetchJSON<{ ok: boolean; mode: string; seeded: number; total_bundled: number }>(
        "/api/onboarding/skills",
        {
          method: "POST",
          body: JSON.stringify({ mode }),
          headers: { "Content-Type": "application/json" },
        },
      ),
  };
}

export type ToolsApi = ReturnType<typeof createToolsApi>;
