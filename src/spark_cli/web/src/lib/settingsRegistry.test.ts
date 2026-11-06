import { describe, expect, it } from "vitest";
import { COMMON_SETTINGS, PAGE_DESTINATIONS, SETTINGS_SECTIONS, resolveAppDestination, resolveSettingsDestination, schemaSettings, searchSettings, settingBreadcrumb } from "./settingsRegistry";

describe("shared destination registry", () => {
  it("has unique page, section and control identities and resolves every palette destination", () => {
    const ids = [...PAGE_DESTINATIONS.map((item) => `page:${item.id}`), ...SETTINGS_SECTIONS.map((item) => item.id), ...COMMON_SETTINGS.map((item) => item.id)];
    expect(new Set(ids).size).toBe(ids.length);
    for (const item of PAGE_DESTINATIONS) expect(resolveAppDestination(item.id)).toEqual({ page: item.id });
    for (const item of SETTINGS_SECTIONS.filter((item) => item.id !== "chat")) {
      expect(resolveAppDestination(item.id)).toEqual({ settings: item.id });
      expect(resolveSettingsDestination(item.id).section).toBe(item.id);
    }
  });
  it("retains old advanced deep links with the correct child, plus provider/skills aliases", () => {
    for (const child of ["config", "admin", "logs", "analytics"]) expect(resolveSettingsDestination(child)).toMatchObject({ section: "advanced", child });
    expect(resolveSettingsDestination("providers").section).toBe("model");
    expect(resolveSettingsDestination("keys").section).toBe("skills-tools");
    expect(resolveSettingsDestination("skillsTools").section).toBe("skills-tools");
    expect(resolveSettingsDestination("status").section).toBe("gateway");
    expect(resolveSettingsDestination("updates").section).toBe("about");
    expect(resolveAppDestination("memory")).toEqual({ settings: "memory" });
  });
  it("indexes exact schema labels, keys and descriptions including unknown advanced categories", () => {
    const fields = schemaSettings({
      "memory.memory_enabled": { type: "boolean", category: "memory", label: "Remember facts" },
      "compression.threshold": { category: "compression", label: "Compression threshold" },
      "future.setting": { category: "future", label: "Custom control", description: "Synthetic advanced option" },
      "agent.name": { category: "general", label: "Agent name" },
      "terminal.timeout": { category: "terminal" },
      "model_provider": { category: "general" },
    });
    expect(fields).toHaveLength(5);
    expect(searchSettings("Remember facts", fields)).toEqual([expect.objectContaining({ fieldKey: "memory.memory_enabled", section: "memory" })]);
    expect(searchSettings("compression.threshold", fields)[0]).toMatchObject({ fieldKey: "compression.threshold", section: "memory" });
    const future = searchSettings("Synthetic advanced option", fields)[0];
    expect(future).toMatchObject({ fieldKey: "future.setting", section: "advanced", child: "config", category: "future" });
    expect(settingBreadcrumb(future)).toBe("Settings › Advanced › config › future › Custom control");
    expect(searchSettings("Agent name", fields)[0].section).toBe("model");
  });
  it("targets actual common labels and keeps saved MCP and test destinations distinct", () => {
    expect(searchSettings("Model").filter((item) => settingBreadcrumb(item) === "Settings › Model")).toHaveLength(1);
    expect(searchSettings("Model")[0]).toMatchObject({ id: "model-id", controlLabel: "Model" });
    expect(searchSettings("Base URL")[0]).toMatchObject({ section: "model", fieldKey: "model", controlLabel: "Base URL" });
    expect(searchSettings("MCP tests")).toEqual([expect.objectContaining({ section: "mcp-tests" })]);
    expect(searchSettings("Server JSON")[0]).toMatchObject({ section: "mcp", controlLabel: "Server JSON" });
    expect(searchSettings("Completion sounds")[0]).toMatchObject({ section: "notifications", controlLabel: "Completion sounds" });
    expect(searchSettings("Connection").some((item) => item.section === "connection")).toBe(false);
    expect(searchSettings("Connection", [], true).some((item) => item.section === "connection")).toBe(true);
    expect(searchSettings("Schedule")[0]).toMatchObject({ page: "cron" });
    expect(searchSettings("   ")).toEqual([]);
  });
  it("keeps common destinations before secondary sections", () => {
    expect(SETTINGS_SECTIONS.slice(0, 8).map((item) => item.id)).toEqual(["connection", "profiles", "model", "memory", "skills-tools", "mcp", "mcp-tests", "notifications"]);
    // SP24's role UI is an integration gate: the index points at the existing Model destination.
    expect(searchSettings("role mappings")[0]).toMatchObject({ label: "Model", section: "model", controlLabel: "Model" });
  });
});
