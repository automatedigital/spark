/** Metadata only: safe to import in the shell without loading Settings or pages. */
export const PAGE_DESTINATIONS = [
  { id: "chat", label: "Chat", description: "Projects and conversations", labelKey: "chat" },
  { id: "files", label: "Files", description: "Workspace files", labelKey: "files", primary: true },
  { id: "cron", label: "Schedule", description: "Scheduled jobs", labelKey: "cron", primary: true },
  { id: "skills", label: "Skills", description: "Skill manager", labelKey: "skills" },
  { id: "connectors", label: "Connectors", description: "External app connectors", labelKey: "connectors" },
] as const;
export type PageDestinationId = (typeof PAGE_DESTINATIONS)[number]["id"];

export const SETTINGS_SECTIONS = [
  { id: "connection", label: "Connection", desktopOnly: true, common: true },
  { id: "profiles", label: "Profiles", common: true },
  { id: "model", label: "Model", common: true },
  { id: "memory", label: "Memory & Context", common: true },
  { id: "skills-tools", label: "Skills & Tools", common: true },
  { id: "mcp", label: "MCP", common: true },
  { id: "mcp-tests", label: "MCP tests", common: true },
  { id: "notifications", label: "Notifications", common: true },
  { id: "chat", label: "Chat" },
  { id: "appearance", label: "Appearance" },
  { id: "workspace", label: "Workspace" },
  { id: "safety", label: "Safety" },
  { id: "voice", label: "Voice" },
  { id: "gateway", label: "Gateway" },
  { id: "messaging", label: "Messaging Connections" },
  { id: "archived", label: "Archived Chats" },
  { id: "advanced", label: "Advanced" },
  { id: "about", label: "About" },
] as const;
export type SettingsSectionId = (typeof SETTINGS_SECTIONS)[number]["id"];
export type SettingsChildId = "config" | "admin" | "logs" | "analytics";
export interface SettingDestination {
  id: string;
  label: string;
  section: SettingsSectionId;
  child?: SettingsChildId;
  fieldKey?: string;
  controlLabel?: string;
  keywords?: string;
  category?: string;
  page?: PageDestinationId;
}
export const COMMON_SETTINGS: readonly SettingDestination[] = [
  { id: "model-provider", label: "Provider", section: "model", fieldKey: "model", controlLabel: "Provider" },
  { id: "model-id", label: "Model", section: "model", fieldKey: "model", controlLabel: "Model", keywords: "Auto role mappings" },
  { id: "model-endpoint", label: "Base URL", section: "model", fieldKey: "model", controlLabel: "Base URL", keywords: "custom endpoint" },
  { id: "mcp-name", label: "Name", section: "mcp", controlLabel: "Name", keywords: "MCP server" },
  { id: "mcp-json", label: "Server JSON", section: "mcp", controlLabel: "Server JSON", keywords: "MCP saved configuration" },
  { id: "completion-alerts", label: "Completion alerts", section: "notifications", controlLabel: "Completion alerts" },
  { id: "completion-sounds", label: "Completion sounds", section: "notifications", controlLabel: "Completion sounds" },
  { id: "input-sounds", label: "Input request sounds", section: "notifications", controlLabel: "Input request sounds" },
];
const LEGACY_SETTINGS: Record<string, { section: SettingsSectionId; child?: SettingsChildId }> = {
  status: { section: "gateway" }, updates: { section: "about" }, keys: { section: "skills-tools" },
  providers: { section: "model" }, skillsTools: { section: "skills-tools" },
  config: { section: "advanced", child: "config" }, admin: { section: "advanced", child: "admin" },
  logs: { section: "advanced", child: "logs" }, analytics: { section: "advanced", child: "analytics" },
};
export function resolveSettingsDestination(id: string): SettingDestination {
  const control = COMMON_SETTINGS.find((item) => item.id === id);
  if (control) return control;
  const legacy = LEGACY_SETTINGS[id];
  const section = legacy?.section ?? SETTINGS_SECTIONS.find((item) => item.id === id)?.id ?? "model";
  return { id, label: SETTINGS_SECTIONS.find((item) => item.id === section)!.label, section, child: legacy?.child };
}
export function settingBreadcrumb(item: SettingDestination): string {
  if (item.page) return item.label;
  const section = SETTINGS_SECTIONS.find((section) => section.id === item.section)!.label;
  return ["Settings", section, item.child, item.category, item.label === section ? undefined : item.label].filter(Boolean).join(" › ");
}
export function schemaSettings(fields: Record<string, Record<string, unknown>>): SettingDestination[] {
  return Object.entries(fields).filter(([key]) => !["model", "model_provider", "model_base_url"].includes(key)).map(([key, schema]) => {
    const category = String(schema.category ?? "general");
    const section: SettingsSectionId = ["memory", "compression"].includes(category) ? "memory"
      : category === "display" || key === "timezone" ? "chat"
      : ["general", "auxiliary", "curator"].includes(category) && !["file_read_max_chars", "command_allowlist", "prefill_messages_file"].includes(key) ? "model"
      : "advanced";
    return {
      id: `field:${key}`, fieldKey: key, section, child: section === "advanced" ? "config" : undefined,
      category: section === "advanced" ? category : undefined,
      label: typeof schema.label === "string" && schema.label ? schema.label : (key.split(".").pop() ?? key).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      keywords: `${key} ${String(schema.description ?? "")}`,
    };
  });
}
export function searchSettings(query: string, fields: readonly SettingDestination[] = [], desktop = false): SettingDestination[] {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const sections: SettingDestination[] = SETTINGS_SECTIONS.filter((item) => (desktop || !("desktopOnly" in item)) && !COMMON_SETTINGS.some((control) => control.section === item.id && control.label === item.label)).map((item) => ({ id: item.id, section: item.id, label: item.label }));
  const pages: SettingDestination[] = PAGE_DESTINATIONS.map((item) => ({ id: `page:${item.id}`, label: item.label, page: item.id, section: "advanced", keywords: item.description }));
  const normalized = query.trim().toLocaleLowerCase();
  const rank = (item: SettingDestination) => item.label.toLocaleLowerCase() === normalized ? 0
    : item.fieldKey?.toLocaleLowerCase() === normalized ? 1
    : words.every((word) => item.label.toLocaleLowerCase().includes(word)) ? 2 : 3;
  return [...COMMON_SETTINGS, ...sections, ...fields, ...pages]
    .filter((item) => words.every((word) => `${settingBreadcrumb(item)} ${item.keywords ?? ""}`.toLocaleLowerCase().includes(word)))
    .sort((a, b) => rank(a) - rank(b));
}
/** Settings aliases are destinations, never invalid page ids. Existing pages remain valid. */
export function resolveAppDestination(id: string): { page: PageDestinationId } | { settings: string } {
  if (PAGE_DESTINATIONS.some((item) => item.id === id)) return { page: id as PageDestinationId };
  return { settings: id === "messaging" ? "messaging" : id };
}

const COMMON_FIELD_KEYS = new Set(["model", "timezone", "memory.memory_enabled", "memory.user_profile_enabled", "memory.provider", "compression.enabled", "compression.threshold"]);
export function isCommonSetting(key: string) { return COMMON_FIELD_KEYS.has(key); }
