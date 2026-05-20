import { useEffect, useRef, useState, useMemo } from "react";
import {
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
import { getNestedValue, setNestedValue } from "@/lib/nested";
import { useToast } from "@/hooks/useToast";
import { Toast } from "@/components/Toast";
import { AutoField } from "@/components/AutoField";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Select, SelectOption } from "@/components/ui/select";
import { useI18n } from "@/i18n";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const CATEGORY_ICONS: Record<string, string> = {
  general: "⚙️",
  models: "🧭",
  agent: "🤖",
  terminal: "💻",
  display: "🎨",
  delegation: "👥",
  memory: "🧠",
  compression: "📦",
  security: "🔒",
  browser: "🌐",
  voice: "🎙️",
  tts: "🔊",
  stt: "👂",
  logging: "📋",
  discord: "💬",
  auxiliary: "🔧",
};

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
    const providerOptions = (currentProvider: string) => {
      if (!currentProvider || MODEL_PROVIDER_OPTIONS.some((option) => option.value === currentProvider)) {
        return MODEL_PROVIDER_OPTIONS;
      }
      return [
        ...MODEL_PROVIDER_OPTIONS,
        { value: currentProvider, label: currentProvider },
      ];
    };

    return (
      <div className="mb-3 border border-border bg-background/70">
        <div className="flex items-center justify-between gap-4 border-b border-border px-4 py-3">
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-foreground">
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

        <div className="grid gap-4 p-4">
          <div className="grid gap-3 border border-border/80 bg-muted/10 p-3">
            <div>
              <h4 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
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
                <Input
                  value={smartModel}
                  onChange={(e) => updateConfigValue("model", e.target.value)}
                  placeholder="gpt-5.5"
                />
              </div>
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
                        "px-3 py-1 text-xs border transition-colors",
                        reasoningEffort === value
                          ? "border-foreground bg-foreground text-background"
                          : "border-border bg-transparent text-muted-foreground hover:border-foreground/50 hover:text-foreground",
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
            <div className="grid gap-3 border border-border/80 bg-muted/10 p-3">
              <div>
                <h4 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
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
                  <Input
                    value={fastModel}
                    onChange={(e) => updateConfigValue("smart_model_routing.cheap_model.model", e.target.value)}
                    placeholder="gpt-5.4-mini"
                  />
                </div>
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
              <span className="text-base">{CATEGORY_ICONS[cat] || "📄"}</span>
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {prettyCategoryName(cat)}
              </span>
              <div className="flex-1 border-t border-border" />
            </div>
          )}
          {showSection && (
            <div className="flex items-center gap-2 pt-4 pb-2 first:pt-0">
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {SECTION_LABELS[section] ?? section.replace(/_/g, " ")}
              </span>
              <div className="flex-1 border-t border-border" />
            </div>
          )}
          <div className="py-1">
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
    <div className="flex flex-col gap-4">
      <Toast toast={toast} />

      {/* ═══════════════ Header Bar ═══════════════ */}
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <Settings2 className="h-4 w-4 text-muted-foreground" />
          <code className="text-xs text-muted-foreground bg-muted/50 px-2 py-0.5 rounded">
            {t.config.configPath}
          </code>
        </div>
        <div className="flex items-center gap-1.5">
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
        <Card>
          <CardHeader className="py-3 px-4">
            <CardTitle className="text-sm flex items-center gap-2">
              <FileText className="h-4 w-4" />
              {t.config.rawYaml}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            {yamlLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              </div>
            ) : (
              <textarea
                className="flex min-h-[600px] w-full bg-transparent px-4 py-3 text-sm font-mono leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none border-t border-border"
                value={yamlText}
                onChange={(e) => setYamlText(e.target.value)}
                spellCheck={false}
              />
            )}
          </CardContent>
        </Card>
      ) : (
        /* ═══════════════ Form Mode ═══════════════ */
        <div className="flex flex-col sm:flex-row gap-4" style={{ minHeight: "calc(100vh - 180px)" }}>
          {/* ---- Sidebar — horizontal scroll on mobile, fixed column on sm+ ---- */}
          <div className="sm:w-52 sm:shrink-0">
            <div className="sm:sticky sm:top-[72px] flex flex-col gap-1">
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
                    className={`group flex items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition-colors cursor-pointer ${
                      isActive
                        ? "bg-primary/10 text-primary font-medium"
                        : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                    }`}
                  >
                    <span className="text-sm leading-none">{CATEGORY_ICONS[cat] || "📄"}</span>
                    <span className="flex-1 truncate">{prettyCategoryName(cat)}</span>
                    <span className={`text-[10px] tabular-nums ${isActive ? "text-primary/60" : "text-muted-foreground/50"}`}>
                      {categoryCounts[cat] || 0}
                    </span>
                    {isActive && (
                      <ChevronRight className="h-3 w-3 text-primary/50 shrink-0" />
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
              <Card>
                <CardHeader className="py-3 px-4">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <Search className="h-4 w-4" />
                      {t.config.searchResults}
                    </CardTitle>
                    <Badge variant="secondary" className="text-[10px]">
                      {searchMatchedFields.length} {t.config.fields.replace("{s}", searchMatchedFields.length !== 1 ? "s" : "")}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="grid gap-2 px-4 pb-4">
                  {searchMatchedFields.length === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-8">
                      {t.config.noFieldsMatch.replace("{query}", searchQuery)}
                    </p>
                  ) : (
                    renderFields(searchMatchedFields, true)
                  )}
                </CardContent>
              </Card>
            ) : (
              /* Active category */
              <Card>
                <CardHeader className="py-3 px-4">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm flex items-center gap-2">
                      <span className="text-base">{CATEGORY_ICONS[activeCategory] || "📄"}</span>
                      {prettyCategoryName(activeCategory)}
                    </CardTitle>
                    <Badge variant="secondary" className="text-[10px]">
                      {activeFields.length} {t.config.fields.replace("{s}", activeFields.length !== 1 ? "s" : "")}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="grid gap-2 px-4 pb-4">
                  {activeCategory === "general" && renderModelEditor()}
                  {renderFields(activeFields)}
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
