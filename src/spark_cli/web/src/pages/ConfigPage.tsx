import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { createPortal } from "react-dom";
import {
  Check,
  ChevronDown,
  Code,
  Download,
  FormInput,
  RotateCcw,
  Save,
  Search,
  Upload,
  X,
  ChevronRight,
  Settings2,
  FileText,
} from "lucide-react";
import { api } from "@/lib/api";
import type { OAuthProvider } from "@/lib/api";
import { OAuthLoginModal } from "@/components/OAuthLoginModal";
import { getNestedValue, setNestedValue } from "@/lib/nested";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { AutoField } from "@/components/AutoField";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Select, SelectOption } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useI18n } from "@/i18n";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const SECTION_LABELS: Record<string, string> = {
  smart_model_routing: "Multi-model routing",
};

const MODEL_EDITOR_KEYS = new Set([
  "model",
  "model_provider",
  "model_base_url",
  "model_api_mode",
  "model_context_length",
  "agent.reasoning_effort",
  "smart_model_routing.enabled",
  "smart_model_routing.max_simple_chars",
  "smart_model_routing.max_simple_words",
  "smart_model_routing.cheap_model.provider",
  "smart_model_routing.cheap_model.model",
  "smart_model_routing.cheap_model.base_url",
  "smart_model_routing.cheap_model.api_mode",
]);

const REASONING_EFFORT_OPTIONS = [
  { value: "", label: "Default" },
  { value: "minimal", label: "Minimal" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "Max" },
];

const MODEL_PROVIDER_OPTIONS = [
  { value: "", label: "Auto" },
  { value: "openai-codex", label: "OpenAI Codex" },
  { value: "openrouter", label: "OpenRouter" },
  { value: "anthropic", label: "Anthropic" },
  { value: "qwen-oauth", label: "Qwen OAuth" },
  { value: "github-copilot", label: "GitHub Copilot" },
  { value: "copilot-acp", label: "GitHub Copilot ACP" },
  { value: "zai", label: "Z.ai" },
  { value: "kimi-for-coding", label: "Kimi for Coding" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "alibaba", label: "Alibaba DashScope" },
  { value: "minimax", label: "MiniMax" },
  { value: "minimax-cn", label: "MiniMax CN" },
  { value: "xai", label: "xAI" },
  { value: "ollama", label: "Ollama" },
  { value: "custom", label: "Custom" },
];

function configProviderOptions(config: Record<string, unknown> | null) {
  const providers = config?.providers;
  if (!providers || typeof providers !== "object" || Array.isArray(providers)) {
    return [];
  }
  return Object.entries(providers as Record<string, unknown>)
    .filter(
      ([, entry]) => entry && typeof entry === "object" && !Array.isArray(entry),
    )
    .map(([key, entry]) => {
      const provider = entry as Record<string, unknown>;
      const name =
        typeof provider.name === "string" && provider.name.trim()
          ? provider.name.trim()
          : key;
      return { value: key, label: name };
    });
}

// OAuth-backed providers that can be (re)connected from the dashboard. When one
// of these is the selected provider, the model editor surfaces an inline
// connection status + Reconnect button so the user can refresh rotated auth.
const OAUTH_RECONNECT_PROVIDERS = new Set(["openai-codex", "qwen-oauth", "anthropic"]);

const CODEX_MODEL_FALLBACKS = [
  "gpt-5.5",
  "gpt-5.4",
  "gpt-5.4-mini",
  "gpt-5.3-codex",
  "gpt-5.2-codex",
  "gpt-5.1-codex-max",
  "gpt-5.1-codex-mini",
  "gpt-5.3-codex-spark",
];

function SearchableModelSelect({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [menuRect, setMenuRect] = useState<DOMRect | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const selected = value || "";
  const filtered = options.filter((model) =>
    model.toLowerCase().includes(query.trim().toLowerCase()),
  );

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setHighlightedIndex(0);
  }, []);

  const selectModel = useCallback(
    (model: string) => {
      onChange(model);
      close();
    },
    [close, onChange],
  );

  useEffect(() => {
    if (!open) return;
    const update = () => {
      if (rootRef.current) setMenuRect(rootRef.current.getBoundingClientRect());
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    const onMouseDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        rootRef.current?.contains(target) ||
        menuRef.current?.contains(target)
      ) {
        return;
      }
      close();
    };
    document.addEventListener("mousedown", onMouseDown);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      document.removeEventListener("mousedown", onMouseDown);
    };
  }, [close, open]);

  useEffect(() => {
    if (!open) return;
    window.setTimeout(() => searchRef.current?.focus(), 0);
  }, [open]);

  useEffect(() => {
    setHighlightedIndex(0);
  }, [query]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (!open && (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      setOpen(true);
      return;
    }
    if (!open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setHighlightedIndex((index) => Math.min(index + 1, filtered.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setHighlightedIndex((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && filtered[highlightedIndex]) {
      event.preventDefault();
      selectModel(filtered[highlightedIndex]);
    }
  };

  return (
    <div ref={rootRef} className="relative" onKeyDown={onKeyDown}>
      <button
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        onClick={() => setOpen((current) => !current)}
        className={cn(
          "flex h-9 w-full items-center justify-between border border-border bg-background/40 px-3 py-1 font-courier text-sm text-left transition-colors",
          "hover:border-foreground/20 hover:bg-foreground/[0.03]",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-foreground/30 focus-visible:border-foreground/25",
          "cursor-pointer",
        )}
      >
        <span className={cn("truncate", !selected && "text-muted-foreground")}>
          {selected || "Select a model..."}
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open &&
        menuRect &&
        createPortal(
          <div
            ref={menuRef}
            style={{
              left: menuRect.left,
              top: menuRect.bottom + 4,
              width: menuRect.width,
            }}
            className={cn(
              "fixed z-[1000] overflow-hidden border border-border bg-card text-card-foreground shadow-2xl",
              "backdrop-blur-sm",
            )}
          >
            <div className="relative border-b border-border bg-background/80">
              <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/60" />
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search models..."
                className={cn(
                  "h-9 w-full bg-transparent pl-9 pr-3 font-courier text-sm text-foreground placeholder:text-muted-foreground",
                  "focus:outline-none",
                )}
              />
            </div>
            <div role="listbox" className="max-h-56 overflow-y-auto py-1">
              {filtered.length === 0 ? (
                <div className="px-3 py-3 text-sm text-muted-foreground">
                  No models found
                </div>
              ) : (
                filtered.map((model, index) => {
                  const isSelected = model === selected;
                  const isHighlighted = index === highlightedIndex;
                  return (
                    <button
                      key={model}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      onMouseEnter={() => setHighlightedIndex(index)}
                      onClick={() => selectModel(model)}
                      className={cn(
                        "flex h-8 w-full items-center gap-2 px-3 text-left font-courier text-sm transition-colors",
                        "cursor-pointer",
                        isHighlighted && "bg-foreground/10 text-foreground",
                        !isHighlighted && "text-muted-foreground hover:bg-foreground/[0.06] hover:text-foreground",
                      )}
                    >
                      <Check
                        className={cn(
                          "h-3.5 w-3.5 shrink-0 text-foreground",
                          isSelected ? "opacity-100" : "opacity-0",
                        )}
                      />
                      <span className="truncate">{model}</span>
                    </button>
                  );
                })
              )}
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}

/**
 * Model name field that adapts to the selected provider:
 *  - Fixed/managed catalogs (openai-codex, qwen-oauth) → strict dropdown.
 *  - Open-ended providers (ollama, openrouter, custom, …) → free-text input
 *    with the known names offered as `datalist` suggestions.
 * The current value is always preserved as a selectable option so an existing
 * or hand-entered config value is never silently dropped.
 */
function ModelField({
  provider,
  value,
  onChange,
  placeholder,
}: {
  provider: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  const [models, setModels] = useState<string[]>([]);
  const [strict, setStrict] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!provider) {
      setModels([]);
      setStrict(false);
      return;
    }
    api
      .getAvailableModels(provider)
      .then((r) => {
        if (cancelled) return;
        const apiModels = Array.isArray(r.models) ? r.models : [];
        const fallbackModels =
          provider === "openai-codex" && apiModels.length === 0 ? CODEX_MODEL_FALLBACKS : [];
        setModels(apiModels.length > 0 ? apiModels : fallbackModels);
        setStrict(!!r.strict || fallbackModels.length > 0);
      })
      .catch(() => {
        if (cancelled) return;
        if (provider === "openai-codex") {
          setModels(CODEX_MODEL_FALLBACKS);
          setStrict(true);
          return;
        }
        setModels([]);
        setStrict(false);
      });
    return () => {
      cancelled = true;
    };
  }, [provider]);

  if (strict && models.length > 0) {
    const options = value && !models.includes(value) ? [...models, value] : models;
    return (
      <SearchableModelSelect value={value} options={options} onChange={onChange} />
    );
  }

  const listId = `model-options-${provider || "none"}`;
  return (
    <>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        list={models.length > 0 ? listId : undefined}
      />
      {models.length > 0 && (
        <datalist id={listId}>
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      )}
    </>
  );
}

/**
 * Inline OAuth connection status + (re)connect control for the selected
 * provider. Renders nothing for non-OAuth providers. Reuses the existing
 * device-code/PKCE flow via OAuthLoginModal so rotated auth can be refreshed
 * without leaving the Config tab.
 */
function ProviderConnection({
  providerId,
  onError,
  onSuccess,
}: {
  providerId: string;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
}) {
  const [provider, setProvider] = useState<OAuthProvider | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const refresh = useCallback(() => {
    api
      .getOAuthProviders()
      .then((r) => setProvider(r.providers.find((p) => p.id === providerId) ?? null))
      .catch(() => setProvider(null));
  }, [providerId]);

  useEffect(() => {
    if (OAUTH_RECONNECT_PROVIDERS.has(providerId)) refresh();
    else setProvider(null);
  }, [providerId, refresh]);

  if (!OAUTH_RECONNECT_PROVIDERS.has(providerId) || !provider) return null;

  const loggedIn = !!provider.status.logged_in;
  return (
    <div className="md:col-span-2 flex items-center justify-between gap-3 border border-border/60 bg-muted/20 px-3 py-2">
      <div className="flex items-center gap-2 text-xs">
        <span
          className={[
            "inline-block h-2 w-2 rounded-full",
            loggedIn ? "bg-emerald-500" : "bg-amber-500",
          ].join(" ")}
          aria-hidden
        />
        <span className="text-muted-foreground">
          {provider.name}{" "}
          {loggedIn ? "connected" : "not connected"}
          {loggedIn && provider.status.token_preview ? (
            <span className="text-muted-foreground/60"> ·{provider.status.token_preview}</span>
          ) : null}
        </span>
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setModalOpen(true)}
      >
        {loggedIn ? "Reconnect" : "Connect"}
      </Button>
      {modalOpen && (
        <OAuthLoginModal
          provider={provider}
          onClose={() => setModalOpen(false)}
          onSuccess={(msg) => {
            setModalOpen(false);
            refresh();
            onSuccess(msg);
          }}
          onError={onError}
        />
      )}
    </div>
  );
}

function textValue(value: unknown): string {
  return value === undefined || value === null ? "" : String(value);
}

function numberValue(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export default function ConfigPage() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [schema, setSchema] = useState<Record<string, Record<string, unknown>> | null>(null);
  const [categoryOrder, setCategoryOrder] = useState<string[]>([]);
  const [defaults, setDefaults] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [yamlMode, setYamlMode] = useState(false);
  const [yamlText, setYamlText] = useState("");
  const [yamlLoading, setYamlLoading] = useState(false);
  const [yamlSaving, setYamlSaving] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>("");
  const { toast, showToast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { t } = useI18n();

  function prettyCategoryName(cat: string): string {
    const key = cat as keyof typeof t.config.categories;
    if (t.config.categories[key]) return t.config.categories[key];
    return cat.charAt(0).toUpperCase() + cat.slice(1);
  }

  useEffect(() => {
    api.getConfig().then(setConfig).catch(() => {});
    api
      .getSchema()
      .then((resp) => {
        setSchema(resp.fields as Record<string, Record<string, unknown>>);
        setCategoryOrder(resp.category_order ?? []);
      })
      .catch(() => {});
    api.getDefaults().then(setDefaults).catch(() => {});
  }, []);

  // Set active category when categories load
  useEffect(() => {
    if (categoryOrder.length > 0 && !activeCategory) {
      setActiveCategory(categoryOrder[0]);
    }
  }, [categoryOrder, activeCategory]);

  // Load YAML when switching to YAML mode
  useEffect(() => {
    if (yamlMode) {
      setYamlLoading(true);
      api
        .getConfigRaw()
        .then((resp) => setYamlText(resp.yaml))
        .catch(() => showToast(t.config.failedToLoadRaw, "error"))
        .finally(() => setYamlLoading(false));
    }
  }, [yamlMode]);

  /* ---- Categories ---- */
  const categories = useMemo(() => {
    if (!schema) return [];
    const allCats = [...new Set(Object.values(schema).map((s) => String(s.category ?? "general")))];
    const ordered = categoryOrder.filter((c) => allCats.includes(c));
    const extra = allCats.filter((c) => !categoryOrder.includes(c)).sort();
    return [...ordered, ...extra];
  }, [schema, categoryOrder]);

  /* ---- Category field counts ---- */
  const categoryCounts = useMemo(() => {
    if (!schema) return {};
    const counts: Record<string, number> = {};
    for (const s of Object.values(schema)) {
      const cat = String(s.category ?? "general");
      counts[cat] = (counts[cat] || 0) + 1;
    }
    return counts;
  }, [schema]);

  /* ---- Search ---- */
  const isSearching = searchQuery.trim().length > 0;
  const lowerSearch = searchQuery.toLowerCase();

  const searchMatchedFields = useMemo(() => {
    if (!isSearching || !schema) return [];
    return Object.entries(schema).filter(([key, s]) => {
      const label = key.split(".").pop() ?? key;
      const humanLabel = label.replace(/_/g, " ");
      return (
        key.toLowerCase().includes(lowerSearch) ||
        humanLabel.toLowerCase().includes(lowerSearch) ||
        String(s.category ?? "").toLowerCase().includes(lowerSearch) ||
        String(s.description ?? "").toLowerCase().includes(lowerSearch)
      );
    });
  }, [isSearching, lowerSearch, schema]);

  /* ---- Active tab fields ---- */
  const activeFields = useMemo(() => {
    if (!schema || isSearching) return [];
    return Object.entries(schema).filter(([key, s]) => {
      if (activeCategory === "general" && MODEL_EDITOR_KEYS.has(key)) return false;
      return String(s.category ?? "general") === activeCategory;
    });
  }, [schema, activeCategory, isSearching]);

  /* ---- Handlers ---- */
  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    try {
      await api.saveConfig(config);
      showToast(t.config.configSaved, "success");
    } catch (e) {
      showToast(`${t.config.failedToSave}: ${e}`, "error");
    } finally {
      setSaving(false);
    }
  };

  const handleYamlSave = async () => {
    setYamlSaving(true);
    try {
      await api.saveConfigRaw(yamlText);
      showToast(t.config.yamlConfigSaved, "success");
      api.getConfig().then(setConfig).catch(() => {});
    } catch (e) {
      showToast(`${t.config.failedToSaveYaml}: ${e}`, "error");
    } finally {
      setYamlSaving(false);
    }
  };

  const handleReset = () => {
    if (defaults) setConfig(structuredClone(defaults));
  };

  const handleExport = () => {
    if (!config) return;
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "spark-config.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const imported = JSON.parse(reader.result as string);
        setConfig(imported);
        showToast(t.config.configImported, "success");
      } catch {
        showToast(t.config.invalidJson, "error");
      }
    };
    reader.readAsText(file);
  };

  const updateConfigValue = (path: string, value: unknown) => {
    if (!config) return;
    setConfig(setNestedValue(config, path, value));
  };

  /* ---- Loading ---- */
  if (!config || !schema) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  const renderModelEditor = () => {
    const multiModelEnabled = !!getNestedValue(config, "smart_model_routing.enabled");
    const smartModel = textValue(getNestedValue(config, "model"));
    const smartProvider = textValue(getNestedValue(config, "model_provider"));
    const smartBaseUrl = textValue(getNestedValue(config, "model_base_url"));
    const smartApiMode = textValue(getNestedValue(config, "model_api_mode"));
    const contextLength = numberValue(getNestedValue(config, "model_context_length"));
    const reasoningEffort = textValue(getNestedValue(config, "agent.reasoning_effort"));
    const fastProvider = textValue(getNestedValue(config, "smart_model_routing.cheap_model.provider"));
    const fastModel = textValue(getNestedValue(config, "smart_model_routing.cheap_model.model"));
    const fastBaseUrl = textValue(getNestedValue(config, "smart_model_routing.cheap_model.base_url"));
    const fastApiMode = textValue(getNestedValue(config, "smart_model_routing.cheap_model.api_mode"));
    const maxSimpleChars = numberValue(getNestedValue(config, "smart_model_routing.max_simple_chars"), 160);
    const maxSimpleWords = numberValue(getNestedValue(config, "smart_model_routing.max_simple_words"), 28);
    const customProviderOptions = configProviderOptions(config);
    const allProviderOptions = [...MODEL_PROVIDER_OPTIONS];
    for (const option of customProviderOptions) {
      if (!allProviderOptions.some((existing) => existing.value === option.value)) {
        allProviderOptions.push(option);
      }
    }
    const providerOptions = (currentProvider: string) => {
      if (!currentProvider || allProviderOptions.some((option) => option.value === currentProvider)) {
        return allProviderOptions;
      }
      return [
        ...allProviderOptions,
        { value: currentProvider, label: currentProvider },
      ];
    };

    return (
      <div className="mb-5 rounded-lg bg-foreground/[0.025] px-4 py-3">
        <div className="flex items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-foreground">
              Model
            </h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Configure a single SMART model, or enable Multi-model routing with a SMART model for complex work and a FAST model for simple requests.
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Label className="text-xs text-muted-foreground">
              Multi-model
            </Label>
            <Switch
              checked={multiModelEnabled}
              onCheckedChange={(checked) => updateConfigValue("smart_model_routing.enabled", checked)}
            />
          </div>
        </div>

        <div className="grid gap-4 pt-4">
          <div className="grid gap-3 border-t border-border pt-4">
            <div>
              <h4 className="text-[13px] font-medium text-foreground">
                SMART model
              </h4>
              <p className="mt-1 text-xs text-muted-foreground/80">
                Used for complex prompts, coding tasks, tool-heavy work, and anything that does not qualify for FAST routing.
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <div className="grid gap-1.5">
                <Label className="text-xs">Provider</Label>
                <Select
                  value={smartProvider}
                  onValueChange={(value) => updateConfigValue("model_provider", value)}
                >
                  {providerOptions(smartProvider).map(({ value, label }) => (
                    <SelectOption key={value} value={value}>
                      {label}
                    </SelectOption>
                  ))}
                </Select>
              </div>
              <div className="grid gap-1.5">
                <Label className="text-xs">Model</Label>
                <ModelField
                  provider={smartProvider}
                  value={smartModel}
                  onChange={(value) => updateConfigValue("model", value)}
                  placeholder="gpt-5.5"
                />
              </div>
              <ProviderConnection
                providerId={smartProvider}
                onError={(msg) => showToast(msg, "error")}
                onSuccess={(msg) => showToast(msg, "success")}
              />
              <div className="grid gap-1.5">
                <Label className="text-xs">Base URL</Label>
                <Input
                  value={smartBaseUrl}
                  onChange={(e) => updateConfigValue("model_base_url", e.target.value)}
                  placeholder="optional"
                />
              </div>
              <div className="grid gap-1.5">
                <Label className="text-xs">API mode</Label>
                <Input
                  value={smartApiMode}
                  onChange={(e) => updateConfigValue("model_api_mode", e.target.value)}
                  placeholder="optional"
                />
              </div>
              <div className="grid gap-1.5 md:col-span-2">
                <Label className="text-xs">Context length override</Label>
                <Input
                  type="number"
                  value={String(contextLength)}
                  onChange={(e) => updateConfigValue("model_context_length", Number(e.target.value || 0))}
                />
              </div>
              <div className="grid gap-1.5 md:col-span-2">
                <Label className="text-xs">Reasoning level</Label>
                <p className="text-xs text-muted-foreground/70">
                  Only applies to reasoning-capable models. Default lets the model decide (typically medium).
                </p>
                <div className="flex flex-wrap gap-1 pt-0.5">
                  {REASONING_EFFORT_OPTIONS.map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => updateConfigValue("agent.reasoning_effort", value)}
                      className={[
                        "rounded-md px-3 py-1 text-xs transition-colors",
                        reasoningEffort === value
                          ? "bg-foreground text-background"
                          : "bg-foreground/6 text-muted-foreground hover:bg-foreground/10 hover:text-foreground",
                      ].join(" ")}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {multiModelEnabled && (
            <div className="grid gap-3 border-t border-border pt-4">
              <div>
                <h4 className="text-[13px] font-medium text-foreground">
                  FAST model
                </h4>
                <p className="mt-1 text-xs text-muted-foreground/80">
                  Used only for short simple requests within the routing limits below.
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="grid gap-1.5">
                  <Label className="text-xs">Provider</Label>
                  <Select
                    value={fastProvider}
                    onValueChange={(value) => updateConfigValue("smart_model_routing.cheap_model.provider", value)}
                  >
                    {providerOptions(fastProvider).map(({ value, label }) => (
                      <SelectOption key={value} value={value}>
                        {label}
                      </SelectOption>
                    ))}
                  </Select>
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Model</Label>
                  <ModelField
                    provider={fastProvider}
                    value={fastModel}
                    onChange={(value) => updateConfigValue("smart_model_routing.cheap_model.model", value)}
                    placeholder="gpt-5.4-mini"
                  />
                </div>
                <ProviderConnection
                  providerId={fastProvider}
                  onError={(msg) => showToast(msg, "error")}
                  onSuccess={(msg) => showToast(msg, "success")}
                />
                <div className="grid gap-1.5">
                  <Label className="text-xs">Base URL</Label>
                  <Input
                    value={fastBaseUrl}
                    onChange={(e) => updateConfigValue("smart_model_routing.cheap_model.base_url", e.target.value)}
                    placeholder="optional"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">API mode</Label>
                  <Input
                    value={fastApiMode}
                    onChange={(e) => updateConfigValue("smart_model_routing.cheap_model.api_mode", e.target.value)}
                    placeholder="optional"
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Max simple characters</Label>
                  <Input
                    type="number"
                    value={String(maxSimpleChars)}
                    onChange={(e) => updateConfigValue("smart_model_routing.max_simple_chars", Number(e.target.value || 0))}
                  />
                </div>
                <div className="grid gap-1.5">
                  <Label className="text-xs">Max simple words</Label>
                  <Input
                    type="number"
                    value={String(maxSimpleWords)}
                    onChange={(e) => updateConfigValue("smart_model_routing.max_simple_words", Number(e.target.value || 0))}
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  /* ---- Context Management card (shown in compression category) ---- */
  const renderContextManagementCard = () => {
    const enabled = getNestedValue(config, "compression.enabled");
    const isEnabled = enabled === true || enabled === "true" || (enabled == null ? true : false);
    const threshold = numberValue(getNestedValue(config, "compression.threshold"), 50);
    const targetRatio = numberValue(getNestedValue(config, "compression.target_ratio"), 20);
    const protectLastN = numberValue(getNestedValue(config, "compression.protect_last_n"), 20);
    return (
      <div className="space-y-5 pb-2">
        <div className="settings-row">
          <div className="space-y-0.5">
            <Label className="text-sm font-medium">Auto-compress context</Label>
            <p className="text-[11px] text-muted-foreground">When enabled, the agent summarises earlier turns once the context fills up, keeping costs in check on long sessions.</p>
          </div>
          <div className="justify-self-start md:justify-self-end">
            <Switch checked={isEnabled} onCheckedChange={(v) => updateConfigValue("compression.enabled", v)} />
          </div>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label className="text-sm font-medium">Compression threshold</Label>
            <span className="text-xs font-mono text-muted-foreground">{threshold}%</span>
          </div>
          <input
            type="range" min={20} max={80} step={5}
            value={threshold}
            onChange={(e) => updateConfigValue("compression.threshold", Number(e.target.value) / 100)}
            className="w-full accent-primary"
          />
          <p className="text-[11px] text-muted-foreground">Compress when context reaches this percentage of the model's limit. Lower = compress earlier = lower per-turn token cost on long sessions.</p>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label className="text-sm font-medium">Target ratio after compression</Label>
            <span className="text-xs font-mono text-muted-foreground">{targetRatio}%</span>
          </div>
          <input
            type="range" min={10} max={50} step={5}
            value={targetRatio}
            onChange={(e) => updateConfigValue("compression.target_ratio", Number(e.target.value) / 100)}
            className="w-full accent-primary"
          />
          <p className="text-[11px] text-muted-foreground">How much of the threshold to preserve as the recent tail after compression. Lower = more aggressive summarisation = fewer tokens retained.</p>
        </div>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <Label className="text-sm font-medium">Protect last N messages</Label>
            <span className="text-xs font-mono text-muted-foreground">{protectLastN}</span>
          </div>
          <input
            type="range" min={5} max={60} step={5}
            value={protectLastN}
            onChange={(e) => updateConfigValue("compression.protect_last_n", Number(e.target.value))}
            className="w-full accent-primary"
          />
          <p className="text-[11px] text-muted-foreground">Never compress the most recent N messages, even when above threshold. Keeps the freshest context always fully visible to the agent.</p>
        </div>
      </div>
    );
  };

  /* ---- Render field list (shared between search & normal) ---- */
  const renderFields = (fields: [string, Record<string, unknown>][], showCategory = false) => {
    let lastSection = "";
    let lastCat = "";
    return fields.map(([key, s]) => {
      const parts = key.split(".");
      const section = parts.length > 1 ? parts[0] : "";
      const cat = String(s.category ?? "general");
      const showCatBadge = showCategory && cat !== lastCat;
      const showSection = !showCategory && section && section !== lastSection && section !== activeCategory;
      lastSection = section;
      lastCat = cat;

      return (
        <div key={key}>
          {showCatBadge && (
            <div className="flex items-center gap-2 pt-4 pb-2 first:pt-0">
              <span className="text-xs font-semibold text-muted-foreground">
                {prettyCategoryName(cat)}
              </span>
            </div>
          )}
          {showSection && (
            <div className="flex items-center gap-2 pt-4 pb-2 first:pt-0">
              <span className="text-xs font-semibold text-muted-foreground">
                {SECTION_LABELS[section] ?? section.replace(/_/g, " ")}
              </span>
            </div>
          )}
          <div className="border-t border-border/70 py-2 first:border-t-0">
            <AutoField
              schemaKey={key}
              schema={s}
              value={getNestedValue(config, key)}
              onChange={(v) => updateConfigValue(key, v)}
            />
          </div>
        </div>
      );
    });
  };

  return (
    <div className="settings-page flex flex-col gap-5">
      <Toast toast={toast} />

      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Settings2 className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-base font-semibold text-foreground">Config</h2>
          </div>
          <p className="mt-1 truncate text-xs text-muted-foreground">{t.config.configPath}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button variant="ghost" size="sm" onClick={handleExport} title={t.config.exportConfig} aria-label={t.config.exportConfig}>
            <Download className="h-3.5 w-3.5" />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => fileInputRef.current?.click()} title={t.config.importConfig} aria-label={t.config.importConfig}>
            <Upload className="h-3.5 w-3.5" />
          </Button>
          <input ref={fileInputRef} type="file" accept=".json" className="hidden" onChange={handleImport} />
          <Button variant="ghost" size="sm" onClick={handleReset} title={t.config.resetDefaults} aria-label={t.config.resetDefaults}>
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>

          <div className="w-px h-5 bg-border mx-1" />

          <Button
            variant={yamlMode ? "default" : "outline"}
            size="sm"
            onClick={() => setYamlMode(!yamlMode)}
            className="gap-1.5"
          >
            {yamlMode ? (
              <>
                <FormInput className="h-3.5 w-3.5" />
                {t.common.form}
              </>
            ) : (
              <>
                <Code className="h-3.5 w-3.5" />
                YAML
              </>
            )}
          </Button>

          {yamlMode ? (
            <Button size="sm" onClick={handleYamlSave} disabled={yamlSaving} className="gap-1.5">
              <Save className="h-3.5 w-3.5" />
              {yamlSaving ? t.common.saving : t.common.save}
            </Button>
          ) : (
            <Button size="sm" onClick={handleSave} disabled={saving} className="gap-1.5">
              <Save className="h-3.5 w-3.5" />
              {saving ? t.common.saving : t.common.save}
            </Button>
          )}
        </div>
      </div>

      {/* ═══════════════ YAML Mode ═══════════════ */}
      {yamlMode ? (
        <div className="overflow-hidden rounded-lg bg-foreground/[0.025]">
          <div className="flex items-center gap-2 border-b border-border px-4 py-3">
            <div className="text-sm font-medium flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t.config.rawYaml}
            </div>
          </div>
          <div className="p-0">
            {yamlLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              </div>
            ) : (
              <textarea
                className="flex min-h-[600px] w-full bg-transparent px-4 py-3 text-sm font-mono leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none"
                value={yamlText}
                onChange={(e) => setYamlText(e.target.value)}
                spellCheck={false}
              />
            )}
          </div>
        </div>
      ) : (
        /* ═══════════════ Form Mode ═══════════════ */
        <div className="flex flex-col gap-5 sm:flex-row" style={{ minHeight: "calc(100vh - 180px)" }}>
          {/* ---- Sidebar — horizontal scroll on mobile, fixed column on sm+ ---- */}
          <div className="sm:w-48 sm:shrink-0">
            <div className="flex flex-col gap-1 sm:sticky sm:top-4">
              {/* Search */}
              <div className="relative mb-2 hidden sm:block">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  className="pl-8 h-8 text-xs"
                  placeholder={t.common.search}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
                {searchQuery && (
                  <button
                    type="button"
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    onClick={() => setSearchQuery("")}
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>

              {/* Category nav — horizontal scroll on mobile */}
              <div className="flex sm:flex-col gap-1 overflow-x-auto sm:overflow-x-visible scrollbar-none pb-1 sm:pb-0">
                {categories.map((cat) => {
                const isActive = !isSearching && activeCategory === cat;
                return (
                  <button
                    key={cat}
                    type="button"
                    onClick={() => {
                      setSearchQuery("");
                      setActiveCategory(cat);
                    }}
                    className={`group flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors cursor-pointer ${
                      isActive
                        ? "bg-foreground/9 text-foreground font-medium"
                        : "text-muted-foreground hover:text-foreground hover:bg-foreground/6"
                    }`}
                  >
                    <span className="flex-1 truncate">{prettyCategoryName(cat)}</span>
                    <span className={`text-[10px] tabular-nums ${isActive ? "text-foreground/55" : "text-muted-foreground/50"}`}>
                      {categoryCounts[cat] || 0}
                    </span>
                    {isActive && (
                      <ChevronRight className="h-3 w-3 text-foreground/50 shrink-0" />
                    )}
                  </button>
                );
              })}
              </div>
            </div>
          </div>

          {/* ---- Content ---- */}
          <div className="flex-1 min-w-0">
            {isSearching ? (
              /* Search results */
              <div>
                <div className="border-b border-border pb-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold flex items-center gap-2">
                      <Search className="h-4 w-4" />
                      {t.config.searchResults}
                    </div>
                    <Badge variant="secondary" className="text-[10px]">
                      {searchMatchedFields.length} {t.config.fields.replace("{s}", searchMatchedFields.length !== 1 ? "s" : "")}
                    </Badge>
                  </div>
                </div>
                <div className="grid gap-0 pt-2">
                  {searchMatchedFields.length === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-8">
                      {t.config.noFieldsMatch.replace("{query}", searchQuery)}
                    </p>
                  ) : (
                    renderFields(searchMatchedFields, true)
                  )}
                </div>
              </div>
            ) : (
              /* Active category */
              <div>
                <div className="border-b border-border pb-3">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-semibold flex items-center gap-2">
                      {prettyCategoryName(activeCategory)}
                    </div>
                    <Badge variant="secondary" className="text-[10px]">
                      {activeFields.length} {t.config.fields.replace("{s}", activeFields.length !== 1 ? "s" : "")}
                    </Badge>
                  </div>
                </div>
                <div className="grid gap-0 pt-3">
                  {activeCategory === "general" && renderModelEditor()}
                  {activeCategory === "compression" && renderContextManagementCard()}
                  {activeCategory !== "compression" && renderFields(activeFields)}
                  {activeCategory === "compression" && activeFields.length > 0 && (
                    <details className="mt-2">
                      <summary className="text-[11px] text-muted-foreground cursor-pointer select-none">Advanced fields</summary>
                      <div className="mt-2 grid gap-2">{renderFields(activeFields)}</div>
                    </details>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
