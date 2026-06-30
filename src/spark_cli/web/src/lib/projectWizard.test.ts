import { describe, expect, it } from "vitest";
import type { ProjectTemplate } from "@/lib/api";
import { chooseDefaultStarter, toggleProjectWizardValue } from "@/lib/projectWizard";

function starter(overrides: Partial<ProjectTemplate> & Pick<ProjectTemplate, "id">): ProjectTemplate {
  return {
    id: overrides.id,
    label: overrides.id,
    description: "",
    project_type: "web_application",
    recommended: false,
    available: true,
    package_managers: ["pnpm", "npm"],
    default_package_manager: "pnpm",
    supported_options: [],
    recommended_skills: [],
    ...overrides,
  };
}

describe("project wizard helpers", () => {
  it("prefers the recommended available starter", () => {
    const selected = chooseDefaultStarter([
      starter({ id: "nextjs", recommended: true, available: false }),
      starter({ id: "webapp", recommended: true, available: true }),
      starter({ id: "sveltekit", available: true }),
    ]);

    expect(selected?.id).toBe("webapp");
  });

  it("falls back to the first available starter", () => {
    const selected = chooseDefaultStarter([
      starter({ id: "nextjs", available: false }),
      starter({ id: "webapp", available: true }),
    ]);

    expect(selected?.id).toBe("webapp");
  });

  it("toggles selection values without mutating the original array", () => {
    const original = ["prettier"];
    expect(toggleProjectWizardValue(original, "docker")).toEqual(["prettier", "docker"]);
    expect(toggleProjectWizardValue(original, "prettier")).toEqual([]);
    expect(original).toEqual(["prettier"]);
  });
});
