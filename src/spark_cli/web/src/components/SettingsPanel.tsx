import { useState, useEffect, useMemo, useRef } from "react";
import {
  X,
  Archive,
  Brain,
  Check,
  ChevronDown,
  Cpu,
  Info,
  KeyRound,
  Loader2,
  MessageCircle,
  Mic,
  Monitor,
  Network,
  Palette,
  Plug,
  Radio,
  RefreshCw,
  Shield,
  SlidersHorizontal,
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
import { Select, SelectOption } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";

/* ------------------------------------------------------------------ */
/*  Schema-driven config section                                       */
/*  Renders only the config fields belonging to the given schema       */
/*  categories (plus explicit key includes/excludes) with a Save       */
/*  button — used by the Model / Chat / Workspace / Safety /           */
/*  Memory & Context / Voice sections.                                 */
/* ------------------------------------------------------------------ */

/* Provider list — must mirror the model_provider select options in
 * web_server.py (_SCHEMA_OVERRIDES). */
const PROVIDER_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "(none)" },
  { value: "openai-codex", label: "OpenAI Codex (ChatGPT)" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "anthropic", label: "Anthropic (Claude)" },
  { value: "qwen-oauth", label: "Qwen (OAuth)" },
  { value: "github-copilot", label: "GitHub Copilot" },
  { value: "copilot-acp", label: "Copilot (ACP)" },
  { value: "zai", label: "Z.AI" },
  { value: "kimi-for-coding", label: "Kimi for Coding" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "alibaba", label: "Alibaba" },
  { value: "minimax", label: "MiniMax" },
  { value: "minimax-cn", label: "MiniMax (CN)" },
  { value: "xai", label: "xAI" },
  { value: "ollama", label: "Ollama (local)" },
  { value: "custom", label: "Custom (OpenAI-compatible)" },
];

// Providers whose models are reached over an HTTP base URL the user controls.
const BASE_URL_PROVIDERS = new Set(["ollama", "custom", "openrouter"]);
// Providers with a single canonical endpoint — always set on selection,
// overwriting whatever was there (e.g. OpenRouter only has one host).
const PROVIDER_FIXED_BASE_URL: Record<string, string> = {
  openrouter: "https://openrouter.ai/api/v1",
};
// Default base URLs pre-filled only when the field is empty or still holds a
// canonical default (so a user's custom LAN address isn't clobbered).
const PROVIDER_DEFAULT_BASE_URL: Record<string, string> = {
  ollama: "http://localhost:11434",
};
const _CANONICAL_BASE_URLS = new Set([
  ...Object.values(PROVIDER_FIXED_BASE_URL),
  ...Object.values(PROVIDER_DEFAULT_BASE_URL),
]);
// Providers that authenticate with an API key stored in .env (key → env var).
const PROVIDER_API_KEY_ENV: Record<string, string> = {
  openrouter: "OPENROUTER_API_KEY",
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  deepseek: "DEEPSEEK_API_KEY",
  xai: "XAI_API_KEY",
};

/* Searchable model dropdown that pulls the live catalog from the provider.
 * Always a dropdown (never a bare text box); a typed query that doesn't match
 * can still be applied as a custom model name. */
function ModelCombobox({
  value,
  provider,
  baseUrl,
  onChange,
}: {
  value: string;
  provider: string;
  baseUrl: string;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [live, setLive] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  const load = () => {
    if (!provider) {
      setModels([]);
      setLive(false);
      return;
    }
    setLoading(true);
    api
      .getAvailableModels(provider, baseUrl || undefined)
      .then((r) => {
        setModels(r.models);
        setLive(r.live);
      })
      .catch(() => {
        setModels([]);
        setLive(false);
      })
      .finally(() => setLoading(false));
  };

  // Refetch whenever the provider or base URL changes.
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, baseUrl]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const options = value && !models.includes(value) ? [value, ...models] : models;
  const filtered = search
    ? options.filter((m) => m.toLowerCase().includes(search.toLowerCase()))
    : options;
  const canUseCustom = search.trim() && !options.includes(search.trim());

  const pick = (v: string) => {
    onChange(v);
    setOpen(false);
    setSearch("");
  };

  return (
    <div className="grid gap-1.5">
      <div className="flex items-center justify-between">
        <Label className="text-sm">Model</Label>
        <button
          type="button"
          onClick={load}
          disabled={!provider || loading}
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40"
          title="Refresh model list from provider"
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
          Refresh
        </button>
      </div>
      <span className="text-xs text-muted-foreground/70">
        {provider
          ? live
            ? `Pulled live from ${provider}.`
            : loading
              ? "Loading models…"
              : `Couldn't reach ${provider} — showing suggestions. Check the base URL / API key.`
          : "Select a provider first."}
      </span>
      <div ref={ref} className="relative">
        <button
          type="button"
          disabled={!provider}
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center justify-between rounded-md border border-input bg-background px-2.5 py-2 text-sm transition hover:border-border focus:outline-none disabled:opacity-50"
        >
          <span className="truncate">
            {value || <span className="text-muted-foreground/40">Select model…</span>}
          </span>
          <ChevronDown
            className={`h-3.5 w-3.5 shrink-0 text-muted-foreground/40 transition-transform ${open ? "rotate-180" : ""}`}
          />
        </button>
        {open && (
          <div className="absolute top-full z-[70] mt-1 w-full overflow-hidden rounded-md border border-border bg-popover shadow-xl">
            <div className="border-b border-border px-2 py-1.5">
              <input
                autoFocus
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") setOpen(false);
                  if (e.key === "Enter") {
                    if (filtered.length === 1) pick(filtered[0]);
                    else if (canUseCustom) pick(search.trim());
                  }
                }}
                placeholder="Search or type a model name…"
                className="w-full bg-transparent text-xs text-foreground placeholder:text-muted-foreground/40 focus:outline-none"
              />
            </div>
            <div className="max-h-[220px] overflow-y-auto py-1">
              {filtered.map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => pick(m)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition hover:bg-secondary"
                >
                  <Check className={`h-3 w-3 shrink-0 ${m === value ? "text-primary" : "opacity-0"}`} />
                  <span className="truncate font-mono text-xs">{m}</span>
                </button>
              ))}
              {canUseCustom && (
                <button
                  type="button"
                  onClick={() => pick(search.trim())}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition hover:bg-secondary"
                >
                  <Check className="h-3 w-3 shrink-0 opacity-0" />
                  <span className="truncate text-xs">
                    Use custom: <span className="font-mono">{search.trim()}</span>
                  </span>
                </button>
              )}
              {filtered.length === 0 && !canUseCustom && (
                <div className="px-3 py-2 text-xs text-muted-foreground/40">
                  {provider ? "No models found" : "Select a provider"}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* API-key input for key-authenticated providers. Reads the redacted state from
 * /api/env and saves immediately (the .env store, not config.yaml). */
function ProviderApiKeyField({ envVar }: { envVar: string }) {
  const [isSet, setIsSet] = useState(false);
  const [redacted, setRedacted] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const { toast, showToast } = useToast();

  const reload = () => {
    api
      .getEnvVars()
      .then((vars) => {
        const info = vars[envVar];
        setIsSet(!!info?.is_set);
        setRedacted(info?.redacted_value ?? null);
      })
      .catch(() => {});
  };
  useEffect(reload, [envVar]);

  const save = async () => {
    if (!value.trim()) return;
    setSaving(true);
    try {
      await api.setEnvVar(envVar, value.trim());
      showToast("API key saved", "success");
      setValue("");
      reload();
    } catch (e) {
      showToast(`Failed to save key: ${e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid gap-1.5">
      <Toast toast={toast} />
      <Label className="text-sm">API key</Label>
      <span className="text-xs text-muted-foreground/70">
        Stored in <span className="font-mono">{envVar}</span>.{" "}
        {isSet ? `Currently set (${redacted ?? "••••"}).` : "Not set."}
      </span>
      <div className="flex gap-2">
        <Input
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={isSet ? "Enter a new key to replace" : "Paste API key"}
          onKeyDown={(e) => {
            if (e.key === "Enter") void save();
          }}
        />
        <Button size="sm" onClick={() => void save()} disabled={saving || !value.trim()}>
          {saving ? "Saving…" : "Save key"}
        </Button>
      </div>
    </div>
  );
}

/* Provider + model + base URL + API key editor. Shares the parent form's
 * config object so it saves through the same "Save changes" button (the API
 * key is the one exception — it persists to .env immediately). */
function ModelProviderBlock({
  config,
  setConfig,
}: {
  config: Record<string, unknown>;
  setConfig: (updater: (c: Record<string, unknown> | null) => Record<string, unknown> | null) => void;
}) {
  const provider = String(getNestedValue(config, "model_provider") ?? "");
  const model = String(getNestedValue(config, "model") ?? "");
  const baseUrl = String(getNestedValue(config, "model_base_url") ?? "");

  const setKey = (key: string, v: unknown) =>
    setConfig((c) => (c ? setNestedValue(c, key, v) : c));

  const onProviderChange = (next: string) => {
    setConfig((c) => {
      if (!c) return c;
      let updated = setNestedValue(c, "model_provider", next);
      const currentBase = String(getNestedValue(c, "model_base_url") ?? "");
      const isCanonical = _CANONICAL_BASE_URLS.has(currentBase);
      const fixed = PROVIDER_FIXED_BASE_URL[next];
      const fallback = PROVIDER_DEFAULT_BASE_URL[next];
      if (fixed) {
        // Single-endpoint provider — always pin to its canonical URL.
        updated = setNestedValue(updated, "model_base_url", fixed);
      } else if (fallback && (!currentBase || isCanonical)) {
        // Fill a default only when empty or still a canonical default, so a
        // custom LAN address (e.g. a remote Ollama host) is preserved.
        updated = setNestedValue(updated, "model_base_url", fallback);
      } else if (!BASE_URL_PROVIDERS.has(next) && isCanonical) {
        // Switching to a hosted provider that needs no base URL — clear stale
        // canonical values (but leave custom ones alone).
        updated = setNestedValue(updated, "model_base_url", "");
      }
      return updated;
    });
  };

  const apiKeyEnv = PROVIDER_API_KEY_ENV[provider];

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-1.5">
        <Label className="text-sm">Provider</Label>
        <span className="text-xs text-muted-foreground/70">
          SMART model provider. Selecting Ollama or OpenRouter pulls the available models below.
        </span>
        <Select value={provider} onValueChange={onProviderChange}>
          {PROVIDER_OPTIONS.map((opt) => (
            <SelectOption key={opt.value} value={opt.value}>
              {opt.label}
            </SelectOption>
          ))}
        </Select>
      </div>

      {BASE_URL_PROVIDERS.has(provider) && (
        <div className="grid gap-1.5">
          <Label className="text-sm">Base URL</Label>
          <span className="text-xs text-muted-foreground/70">
            Endpoint Spark queries for the model list and completions.
          </span>
          <Input
            value={baseUrl}
            onChange={(e) => setKey("model_base_url", e.target.value)}
            placeholder="http://localhost:11434"
          />
        </div>
      )}

      {apiKeyEnv && <ProviderApiKeyField envVar={apiKeyEnv} />}

      <ModelCombobox
        value={model}
        provider={provider}
        baseUrl={baseUrl}
        onChange={(v) => setKey("model", v)}
      />
    </div>
  );
}

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
      {fields.map(([key, s]) => {
        // The model / provider / base-URL trio is rendered by a single
        // provider-aware editor (dropdown that pulls live models), so swap the
        // generic AutoField for ModelProviderBlock at the "model" anchor and
        // skip the other two keys it handles.
        if (key === "model_provider" || key === "model_base_url") return null;
        if (key === "model") {
          return (
            <div key={key} className="border-t border-border/60 py-3 first:border-t-0 first:pt-0">
              <ModelProviderBlock config={config} setConfig={setConfig} />
            </div>
          );
        }
        return (
          <div key={key} className="border-t border-border/60 py-3 first:border-t-0 first:pt-0">
            <AutoField
              schemaKey={key}
              schema={s}
              value={getNestedValue(config, key)}
              onChange={(v) => setConfig((c) => (c ? setNestedValue(c, key, v) : c))}
            />
          </div>
        );
      })}
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
  const { toast, showToast } = useToast();
  return (
    <div className="flex flex-col gap-10">
      <ConfigSectionForm
        categories={["general", "auxiliary", "curator"]}
        excludeKeys={NON_MODEL_GENERAL_KEYS}
        intro="Applies to new sessions. Use the model picker in the composer to hot-swap the active chat."
      />
      <div className="mx-auto w-full max-w-2xl border-t border-border pt-8">
        <Toast toast={toast} />
        <div className="mb-3">
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
    </div>
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
  providers: "model", // Providers merged into the Model section.
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
