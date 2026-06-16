import { useState, useEffect, useMemo } from "react";
import {
  X,
  Archive,
  Brain,
  Cpu,
  Info,
  KeyRound,
  MessageCircle,
  Mic,
  Monitor,
  Network,
  Palette,
  Plug,
  Radio,
  Shield,
  SlidersHorizontal,
  Sparkles,
  Wrench,
} from "lucide-react";
import StatusPage from "@/pages/StatusPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import LogsPage from "@/pages/LogsPage";
import AdminPage from "@/pages/AdminPage";
import ConfigPage from "@/pages/ConfigPage";
import EnvPage from "@/pages/EnvPage";
import UpdatesPage from "@/pages/UpdatesPage";
import AppearancePage from "@/pages/AppearancePage";
import MemoryPage from "@/pages/MemoryPage";
import {
  api,
  getConnectionMode,
  getRemoteBaseUrl,
  setRemoteConnection,
  setLocalConnection,
} from "@/lib/api";
import { validateRemoteConnection, displayHost } from "@/lib/connection";
import { isTauri } from "@/sidecar";
import type { McpServersResponse } from "@/lib/api";
import { getNestedValue, setNestedValue } from "@/lib/nested";
import { AutoField } from "@/components/AutoField";
import { OAuthProvidersCard } from "@/components/OAuthProvidersCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";

/* ------------------------------------------------------------------ */
/*  Schema-driven config section                                       */
/*  Renders only the config fields belonging to the given schema       */
/*  categories (plus explicit key includes/excludes) with a Save       */
/*  button — used by the Model / Chat / Workspace / Safety /           */
/*  Memory & Context / Voice sections.                                 */
/* ------------------------------------------------------------------ */

interface ConfigSectionFormProps {
  categories: string[];
  includeKeys?: string[];
  excludeKeys?: string[];
  intro?: string;
}

function ConfigSectionForm({ categories, includeKeys = [], excludeKeys = [], intro }: ConfigSectionFormProps) {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [schema, setSchema] = useState<Record<string, Record<string, unknown>> | null>(null);
  const [saving, setSaving] = useState(false);
  const { toast, showToast } = useToast();

  useEffect(() => {
    api.getConfig().then(setConfig).catch(() => {});
    api
      .getSchema()
      .then((resp) => setSchema(resp.fields as Record<string, Record<string, unknown>>))
      .catch(() => {});
  }, []);

  const fields = useMemo(() => {
    if (!schema) return [] as [string, Record<string, unknown>][];
    const exclude = new Set(excludeKeys);
    const include = new Set(includeKeys);
    const byCategory: Record<string, [string, Record<string, unknown>][]> = {};
    const included: [string, Record<string, unknown>][] = [];
    for (const [key, s] of Object.entries(schema)) {
      if (exclude.has(key)) continue;
      const cat = String(s.category ?? "general");
      if (include.has(key)) {
        included.push([key, s]);
        continue;
      }
      if (!categories.includes(cat)) continue;
      (byCategory[cat] ??= []).push([key, s]);
    }
    const ordered: [string, Record<string, unknown>][] = [];
    for (const cat of categories) ordered.push(...(byCategory[cat] ?? []));
    ordered.push(...included);
    return ordered;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema, categories.join(","), includeKeys.join(","), excludeKeys.join(",")]);

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await api.saveConfig(config);
      showToast("Settings saved", "success");
    } catch (e) {
      showToast(`Failed to save: ${e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  if (!config || !schema) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-1">
      <Toast toast={toast} />
      {intro && <p className="pb-3 text-xs text-muted-foreground">{intro}</p>}
      {fields.map(([key, s]) => (
        <div key={key} className="border-t border-border/60 py-3 first:border-t-0 first:pt-0">
          <AutoField
            schemaKey={key}
            schema={s}
            value={getNestedValue(config, key)}
            onChange={(v) => setConfig((c) => (c ? setNestedValue(c, key, v) : c))}
          />
        </div>
      ))}
      {fields.length === 0 && (
        <p className="py-8 text-center text-sm text-muted-foreground">No settings in this section.</p>
      )}
      <div className="sticky bottom-0 flex justify-end border-t border-border bg-background/80 py-3 backdrop-blur">
        <Button size="sm" onClick={handleSave} disabled={saving}>
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Providers — OAuth account connections                              */
/* ------------------------------------------------------------------ */

function ProvidersSection() {
  const { toast, showToast } = useToast();
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-3">
      <Toast toast={toast} />
      <div>
        <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Plug className="h-4 w-4 text-muted-foreground" />
          Connect an account
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Sign in with a subscription or API key. Spark runs the sign-in flow for you, right here in the app.
        </p>
      </div>
      <OAuthProvidersCard
        onError={(msg) => showToast(msg, "error")}
        onSuccess={(msg) => showToast(msg, "success")}
      />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  MCP servers                                                        */
/* ------------------------------------------------------------------ */

const MCP_JSON_TEMPLATE = `{
  "command": "",
  "args": [],
  "env": {}
}`;

function McpSection() {
  const [servers, setServers] = useState<McpServersResponse | null>(null);
  const [name, setName] = useState("");
  const [json, setJson] = useState(MCP_JSON_TEMPLATE);
  const [saving, setSaving] = useState(false);
  const { toast, showToast } = useToast();

  const reload = () => {
    api.getMcpServers().then(setServers).catch(() => setServers({ ok: false, servers: {} }));
  };
  useEffect(reload, []);

  const handleSave = async () => {
    if (!name.trim()) {
      showToast("Server name is required", "error");
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(json) as Record<string, unknown>;
    } catch {
      showToast("Server JSON is not valid JSON", "error");
      return;
    }
    setSaving(true);
    try {
      await api.addMcpServer({
        name: name.trim(),
        url: typeof parsed.url === "string" ? parsed.url : null,
        command: typeof parsed.command === "string" && parsed.command ? parsed.command : null,
        args: Array.isArray(parsed.args) ? (parsed.args as string[]) : undefined,
        env:
          parsed.env && typeof parsed.env === "object"
            ? (parsed.env as Record<string, string>)
            : undefined,
      });
      showToast(`Saved MCP server "${name.trim()}"`, "success");
      setName("");
      setJson(MCP_JSON_TEMPLATE);
      reload();
    } catch (e) {
      showToast(`Failed to save server: ${e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const entries = Object.entries(servers?.servers ?? {});

  return (
    <div className="mx-auto grid w-full max-w-3xl gap-8 md:grid-cols-2">
      <Toast toast={toast} />

      {/* Existing servers */}
      <div className="flex min-h-40 flex-col">
        {entries.length === 0 ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-1 py-10 text-center">
            <p className="text-sm font-medium text-foreground">No MCP servers</p>
            <p className="text-xs text-muted-foreground">Add a stdio or HTTP server to expose MCP tools.</p>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {entries.map(([serverName, cfg]) => (
              <div key={serverName} className="rounded-md border border-border bg-card/40 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-foreground">{serverName}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 text-xs text-muted-foreground hover:text-red-400"
                    onClick={() =>
                      void api
                        .deleteMcpServer(serverName, window.confirm(`Remove MCP server ${serverName}?`))
                        .then(reload)
                        .catch((e) => showToast(String(e), "error"))
                    }
                  >
                    Remove
                  </Button>
                </div>
                <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-muted-foreground">
                  {JSON.stringify(cfg, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* New server */}
      <div className="flex flex-col gap-3">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Wrench className="h-4 w-4 text-muted-foreground" />
          New server
        </h3>
        <div className="grid gap-1.5">
          <label className="text-xs text-muted-foreground">Name</label>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="filesystem" />
        </div>
        <div className="grid gap-1.5">
          <label className="text-xs text-muted-foreground">Server JSON</label>
          <textarea
            value={json}
            onChange={(e) => setJson(e.target.value)}
            spellCheck={false}
            className="min-h-44 w-full rounded-md border border-border bg-background/40 px-3 py-2 font-mono text-xs leading-relaxed text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30"
          />
        </div>
        <div className="flex justify-end">
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save server"}
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Archived chats                                                     */
/* ------------------------------------------------------------------ */

function ArchivedChatsSection() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div>
        <h3 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Archive className="h-4 w-4 text-muted-foreground" />
          Archived sessions
        </h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Archived chats are hidden from the sidebar but keep all their messages.
        </p>
      </div>
      <div className="flex flex-col items-center justify-center gap-1 py-14 text-center">
        <p className="text-sm font-medium text-foreground">Nothing archived</p>
        <p className="text-xs text-muted-foreground">Archive a chat to hide it here.</p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Memory & Context — settings + stored memories browser              */
/* ------------------------------------------------------------------ */

function MemoryContextSection() {
  return (
    <div className="flex flex-col gap-10">
      <ConfigSectionForm categories={["memory", "compression"]} />
      <div className="mx-auto w-full max-w-2xl border-t border-border pt-6">
        <MemoryPage />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Section registry                                                   */
/* ------------------------------------------------------------------ */

// Keys surfaced in the Model section that the schema files under "general"
// but that belong to other sections in the new layout.
const NON_MODEL_GENERAL_KEYS = [
  "timezone",
  "file_read_max_chars",
  "command_allowlist",
  "prefill_messages_file",
];

function ModelSection() {
  return (
    <ConfigSectionForm
      categories={["general", "auxiliary", "curator"]}
      excludeKeys={NON_MODEL_GENERAL_KEYS}
      intro="Applies to new sessions. Use the model picker in the composer to hot-swap the active chat."
    />
  );
}

function ChatSection() {
  return <ConfigSectionForm categories={["display"]} includeKeys={["timezone"]} />;
}

function WorkspaceSection() {
  return <ConfigSectionForm categories={["terminal"]} includeKeys={["file_read_max_chars"]} />;
}

function SafetySection() {
  return <ConfigSectionForm categories={["security"]} includeKeys={["command_allowlist"]} />;
}

function VoiceSection() {
  return <ConfigSectionForm categories={["voice", "tts", "stt"]} />;
}

/* Desktop-only: switch between running Spark locally vs connecting to a
 * remote instance (VPS). Mirrors the onboarding remote-connect flow and is
 * the single place to edit/clear the remote URL + token after setup. */
function ConnectionSection() {
  const [mode, setMode] = useState(getConnectionMode());
  const [url, setUrl] = useState(getRemoteBaseUrl() ?? "");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { toast, showToast } = useToast();

  const connectRemote = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await validateRemoteConnection(url, token);
      if (!result.ok) {
        setError(result.error ?? "Could not connect");
        return;
      }
      setRemoteConnection(url, token);
      showToast("Connected. Reloading…", "success");
      setTimeout(() => window.location.reload(), 600);
    } catch (e) {
      setError(`Could not connect: ${e}`);
    } finally {
      setBusy(false);
    }
  };

  const switchToLocal = () => {
    setLocalConnection();
    setMode("local");
    setUrl("");
    setToken("");
    showToast("Switched to Local Mac. Reloading…", "success");
    setTimeout(() => window.location.reload(), 600);
  };

  const currentHost = displayHost(getRemoteBaseUrl());

  return (
    <div className="flex flex-col gap-5 p-6">
      <div>
        <h3 className="text-sm font-semibold">Connection</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          {mode === "remote"
            ? `Currently connected to a remote Spark instance${currentHost ? ` @ ${currentHost}` : ""}.`
            : "Currently running Spark locally on this Mac."}
        </p>
      </div>

      <div className="flex gap-2">
        <Button
          variant={mode === "local" ? "default" : "outline"}
          size="sm"
          onClick={mode === "local" ? undefined : switchToLocal}
        >
          <Cpu className="mr-1.5 h-4 w-4" /> Local Mac
        </Button>
        <Button
          variant={mode === "remote" ? "default" : "outline"}
          size="sm"
          onClick={() => setMode("remote")}
        >
          <Network className="mr-1.5 h-4 w-4" /> Remote (VPS)
        </Button>
      </div>

      {mode === "remote" && (
        <div className="flex max-w-md flex-col gap-3">
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-muted-foreground">Dashboard URL</span>
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://spark.example.com"
            />
          </label>
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-muted-foreground">Access token</span>
            <Input
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder="dashboard token"
            />
          </label>
          {error && <p className="text-xs text-red-400">{error}</p>}
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={busy || !url.trim() || !token.trim()}
              onClick={connectRemote}
            >
              {busy ? "Connecting…" : "Connect & save"}
            </Button>
            {getConnectionMode() === "remote" && (
              <Button size="sm" variant="outline" onClick={switchToLocal}>
                Clear &amp; use Local
              </Button>
            )}
          </div>
        </div>
      )}
      <Toast toast={toast} />
    </div>
  );
}

interface SectionChild {
  id: string;
  label: string;
  component: React.ComponentType;
}

interface SectionDef {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  component?: React.ComponentType;
  children?: SectionChild[];
}

const SECTION_GROUPS: SectionDef[][] = [
  [
    { id: "model", label: "Model", icon: Cpu, component: ModelSection },
    { id: "chat", label: "Chat", icon: MessageCircle, component: ChatSection },
    { id: "appearance", label: "Appearance", icon: Palette, component: AppearancePage },
    { id: "workspace", label: "Workspace", icon: Monitor, component: WorkspaceSection },
    { id: "safety", label: "Safety", icon: Shield, component: SafetySection },
    { id: "memory", label: "Memory & Context", icon: Brain, component: MemoryContextSection },
    { id: "voice", label: "Voice", icon: Mic, component: VoiceSection },
    {
      id: "advanced",
      label: "Advanced",
      icon: SlidersHorizontal,
      children: [
        { id: "config", label: "Settings", component: ConfigPage },
        { id: "admin", label: "Admin", component: AdminPage },
        { id: "logs", label: "Logs", component: LogsPage },
        { id: "analytics", label: "Analytics", component: AnalyticsPage },
      ],
    },
  ],
  [
    // Desktop-only — filtered out on web (no local-sidecar choice there).
    { id: "connection", label: "Connection", icon: Network, component: ConnectionSection },
    { id: "providers", label: "Providers", icon: Sparkles, component: ProvidersSection },
    { id: "gateway", label: "Gateway", icon: Radio, component: StatusPage },
    { id: "tools-keys", label: "Tools & Keys", icon: KeyRound, component: EnvPage },
    { id: "mcp", label: "MCP", icon: Plug, component: McpSection },
    { id: "archived", label: "Archived Chats", icon: Archive, component: ArchivedChatsSection },
  ],
  [{ id: "about", label: "About", icon: Info, component: UpdatesPage }],
];

// Hide the desktop-only "Connection" section when running in a browser.
const VISIBLE_SECTION_GROUPS: SectionDef[][] = isTauri()
  ? SECTION_GROUPS
  : SECTION_GROUPS.map((g) => g.filter((s) => s.id !== "connection"));

const ALL_SECTIONS = SECTION_GROUPS.flat();

type SettingsTabId = (typeof ALL_SECTIONS)[number]["id"];

// Legacy tab ids (pre-Hermes layout) → new section ids, so existing
// callers passing initialTab keep working.
const LEGACY_TAB_MAP: Record<string, SettingsTabId> = {
  status: "gateway",
  analytics: "advanced",
  logs: "advanced",
  admin: "advanced",
  config: "advanced",
  keys: "tools-keys",
  updates: "about",
};

interface SettingsPanelProps {
  onClose: () => void;
  initialTab?: string;
}

export default function SettingsPanel({ onClose, initialTab = "model" }: SettingsPanelProps) {
  const resolvedInitial =
    ALL_SECTIONS.find((s) => s.id === initialTab)?.id ?? LEGACY_TAB_MAP[initialTab] ?? "model";
  const [activeTab, setActiveTab] = useState<SettingsTabId>(resolvedInitial);
  const [activeChild, setActiveChild] = useState<string>("");
  const [animKey, setAnimKey] = useState(0);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);

  const handleTabChange = (id: SettingsTabId) => {
    setActiveTab(id);
    const section = ALL_SECTIONS.find((s) => s.id === id);
    setActiveChild(section?.children?.[0]?.id ?? "");
    setAnimKey((k) => k + 1);
  };

  const handleChildChange = (id: string) => {
    setActiveChild(id);
    setAnimKey((k) => k + 1);
  };

  const activeSection = ALL_SECTIONS.find((s) => s.id === activeTab)!;
  const activeChildDef = activeSection.children?.find((c) => c.id === activeChild) ?? activeSection.children?.[0];
  const ActiveComponent = (activeSection.children ? activeChildDef?.component : activeSection.component)!;
  const headerLabel = activeSection.children
    ? `${activeSection.label} · ${activeChildDef?.label ?? ""}`
    : activeSection.label;

  const renderNavButton = ({ id, label, icon: Icon }: SectionDef, mobile = false) => (
    <button
      key={id}
      type="button"
      role="tab"
      aria-selected={activeTab === id}
      aria-label={label}
      onClick={() => handleTabChange(id)}
      className={
        mobile
          ? `flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition ${
              activeTab === id
                ? "bg-foreground/9 text-foreground"
                : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
            }`
          : `relative flex h-8 shrink-0 items-center gap-2 rounded-md px-2.5 text-[13px] font-medium transition ${
              activeTab === id
                ? "bg-foreground/9 text-foreground"
                : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
            }`
      }
    >
      {!mobile && activeTab === id && (
        <span className="absolute left-0 top-1.5 bottom-1.5 w-px rounded-full bg-foreground/70" />
      )}
      <Icon className={mobile ? "h-3.5 w-3.5" : "h-4 w-4"} />
      {label}
    </button>
  );

  return (
    <>
      <div
        className="fixed inset-0 z-50 bg-black/48 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
        onClick={onClose}
      >
        <div
          className="flex h-[86vh] w-full max-w-6xl overflow-hidden rounded-lg border border-border bg-background/88 shadow-2xl shadow-black/45 backdrop-blur-2xl"
          role="dialog"
          aria-modal="true"
          aria-label="Settings"
          style={{ animation: "fade-in 150ms ease-out" }}
          onClick={(e) => e.stopPropagation()}
        >
          <aside className="hidden w-56 shrink-0 flex-col border-r border-border bg-card/38 p-2 md:flex">
            <div className="flex h-10 items-center px-2">
              <span className="text-sm font-semibold text-foreground">Settings</span>
            </div>
            <div
              className="mt-2 flex min-w-0 flex-1 flex-col gap-1 overflow-y-auto"
              role="tablist"
              aria-label="Settings sections"
            >
              {VISIBLE_SECTION_GROUPS.map((group, gi) => (
                <div key={gi} className="flex flex-col gap-1">
                  {gi > 0 && <div className="mx-2 my-1.5 border-t border-border/70" />}
                  {group.map((section) => (
                    <div key={section.id} className="flex flex-col gap-0.5">
                      {renderNavButton(section)}
                      {section.children && activeTab === section.id && (
                        <div className="ml-5 flex flex-col gap-0.5 border-l border-border/60 pl-2">
                          {section.children.map((child) => (
                            <button
                              key={child.id}
                              type="button"
                              onClick={() => handleChildChange(child.id)}
                              className={`flex h-7 items-center rounded-md px-2 text-left text-xs transition ${
                                activeChildDef?.id === child.id
                                  ? "bg-foreground/9 font-medium text-foreground"
                                  : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
                              }`}
                            >
                              {child.label}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </aside>

          <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-card/34 px-3 backdrop-blur-xl">
              <span className="text-sm font-semibold text-foreground md:hidden">Settings</span>
              <div
                className="flex min-w-0 flex-1 gap-1 overflow-x-auto scrollbar-none md:hidden"
                role="tablist"
                aria-label="Settings sections"
              >
                {VISIBLE_SECTION_GROUPS.flat().map((section) => renderNavButton(section, true))}
              </div>
              <div className="hidden min-w-0 flex-1 items-center gap-2 md:flex">
                <div className="truncate text-sm font-medium text-foreground">{headerLabel}</div>
                {activeSection.children && (
                  <div className="flex shrink-0 gap-1">
                    {activeSection.children.map((child) => (
                      <button
                        key={child.id}
                        type="button"
                        onClick={() => handleChildChange(child.id)}
                        className={`hidden h-6 items-center rounded-md px-2 text-[11px] transition lg:flex ${
                          activeChildDef?.id === child.id
                            ? "bg-foreground/9 text-foreground"
                            : "text-muted-foreground hover:bg-foreground/6 hover:text-foreground"
                        }`}
                      >
                        {child.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <button
                type="button"
                className="ml-auto grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground transition hover:bg-foreground/7 hover:text-foreground"
                onClick={onClose}
                aria-label="Close settings"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto">
              <div
                key={animKey}
                className="mx-auto w-full px-4 py-5 sm:px-8 sm:py-8"
                style={{ animation: "fade-in 120ms ease-out" }}
              >
                <ActiveComponent />
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
