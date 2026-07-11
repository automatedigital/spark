import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowUp, Brain, Check, ChevronDown, FolderOpen, Loader2, Plus, Settings, Square } from "lucide-react";
import { api } from "@/lib/api";
import type { ModelStatusResponse, ModelSuggestionsResponse, WorkspaceProject } from "@/lib/api";
import { shortModelName } from "@/lib/modelName";
import { SlashCommandMenu } from "@/components/chat/SlashCommandMenu";
import { AtFileMenu } from "@/components/chat/AtFileMenu";
import { useTokenEstimate } from "@/hooks/useTokenEstimate";
import type { ContextItem, ContextEstimate } from "@/lib/context";

interface PromptBarProps {
  input: string;
  setInput: (v: string) => void;
  streaming: boolean;
  onSend: () => void;
  onStop: () => void;
  onUploadFiles?: (files: File[]) => Promise<void>;
  onAttachPath?: (path: string, sizeBytes?: number) => void;
  onRemoveContextItem?: (id: string) => void;
  onUpdateContextMode?: (id: string, mode: import("@/lib/context").InclusionMode) => void;
  disabled?: boolean;
  workspaceSlug?: string;
  contextItems?: ContextItem[];
  sessionId?: string | null;
  projectOptions?: WorkspaceProject[];
  selectedProjectSlug?: string;
  onProjectChange?: (slug: string) => void;
  /** Override the idle placeholder text. */
  placeholder?: string;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

interface TokenBudgetIndicatorProps {
  estimate: ContextEstimate | null;
  loading: boolean;
  contextItems?: ContextItem[];
  onRemoveItem?: (id: string) => void;
  onUpdateMode?: (id: string, mode: import("@/lib/context").InclusionMode) => void;
}

function TokenBudgetIndicator({
  estimate,
  loading,
  contextItems = [],
  onRemoveItem,
  onUpdateMode,
}: TokenBudgetIndicatorProps) {
  const [expanded, setExpanded] = useState(false);

  if (loading && !estimate) {
    return (
      <span className="text-[10px] text-muted-foreground/30 tabular-nums">
        <Loader2 className="inline h-2.5 w-2.5 animate-spin mr-0.5" />
      </span>
    );
  }

  if (!estimate) return null;

  const pct = estimate.utilization;
  const colorClass = pct >= 0.95
    ? "text-destructive"
    : pct >= 0.80
    ? "text-yellow-500"
    : "text-muted-foreground/40";

  const label = `${formatTokens(estimate.total_tokens)} / ${formatTokens(estimate.context_window)}`;

  // Large attached items that can be switched to summary (over 10% of context window)
  const bigItems = estimate.warning
    ? contextItems.filter(
        (item) => item.size_bytes > 5_000 && item.inclusion_mode === "full" && item.type === "file"
      )
    : [];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        title="Token budget breakdown"
        className={`text-[10px] tabular-nums transition hover:opacity-80 ${colorClass}`}
      >
        {label}
      </button>
      {expanded && (
        <div className="absolute bottom-full mb-1 right-0 z-50 bg-popover border border-border rounded-lg shadow-lg p-3 text-[11px] w-60">
          <div className="font-medium text-foreground mb-2">Token budget</div>
          {estimate.buckets.map((b) => (
            <div key={b.label} className="flex justify-between text-muted-foreground py-0.5">
              <span>{b.label}</span>
              <span className="tabular-nums">{formatTokens(b.tokens)}</span>
            </div>
          ))}
          <div className="border-t border-border mt-1 pt-1 flex justify-between font-medium text-foreground">
            <span>Total</span>
            <span className={`tabular-nums ${colorClass}`}>{formatTokens(estimate.total_tokens)}</span>
          </div>
          {estimate.warning && (
            <div className={`mt-1.5 text-[10px] rounded px-1.5 py-0.5 ${
              estimate.warning === "limit_exceeded"
                ? "bg-destructive/10 text-destructive"
                : "bg-yellow-500/10 text-yellow-600"
            }`}>
              {estimate.warning === "limit_exceeded" ? "Likely to hit context limit" : "Context may be compressed"}
            </div>
          )}
          {bigItems.length > 0 && (
            <div className="mt-2 border-t border-border pt-2 space-y-1">
              <div className="text-muted-foreground/70 mb-1">Quick fixes</div>
              {bigItems.map((item) => (
                <div key={item.id} className="flex items-center justify-between gap-1">
                  <span className="truncate text-muted-foreground max-w-[120px]" title={item.label ?? item.source_path ?? ""}>
                    {item.label ?? item.source_path?.split("/").pop() ?? "file"}
                  </span>
                  <div className="flex gap-1 shrink-0">
                    {onUpdateMode && (
                      <button
                        type="button"
                        onClick={() => { onUpdateMode(item.id, "summary"); setExpanded(false); }}
                        className="rounded px-1 py-0.5 bg-secondary hover:bg-secondary/80 text-foreground"
                      >
                        → summary
                      </button>
                    )}
                    {onRemoveItem && (
                      <button
                        type="button"
                        onClick={() => { onRemoveItem(item.id); setExpanded(false); }}
                        className="rounded px-1 py-0.5 bg-secondary hover:bg-secondary/80 text-muted-foreground"
                      >
                        remove
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const AT_RE = /(@\S+)/g;
const SLASH_RE = new RegExp("((?:^|(?<=[ \\t]))\\/\\S+)", "gm");

function renderMirror(text: string, cursorPos: number, showCursor: boolean): React.ReactNode[] {
  type Range = { start: number; end: number; text: string };
  const ranges: Range[] = [];

  let m: RegExpExecArray | null;
  AT_RE.lastIndex = 0;
  while ((m = AT_RE.exec(text)) !== null) {
    ranges.push({ start: m.index, end: m.index + m[0].length, text: m[0] });
  }
  SLASH_RE.lastIndex = 0;
  while ((m = SLASH_RE.exec(text)) !== null) {
    ranges.push({ start: m.index, end: m.index + m[0].length, text: m[0] });
  }
  ranges.sort((a, b) => a.start - b.start);

  // Build a flat list of segments with optional cursor injected at cursorPos
  type Seg = { pos: number; content: React.ReactNode; key: string };
  const segs: Seg[] = [];
  let last = 0;
  for (const r of ranges) {
    if (r.start > last) segs.push({ pos: last, content: text.slice(last, r.start), key: `t${last}` });
    segs.push({ pos: r.start, content: <mark key={r.start} className="bg-transparent text-primary font-bold not-italic">{r.text}</mark>, key: `m${r.start}` });
    last = r.end;
  }
  if (last < text.length) segs.push({ pos: last, content: text.slice(last), key: `t${last}` });

  const nodes: React.ReactNode[] = [];
  const cursor = showCursor ? <span key="caret" className="prompt-cursor inline-block w-px h-[1.1em] bg-foreground/70 align-text-bottom" /> : null;
  let emitted = false;

  for (const seg of segs) {
    const content = seg.content;
    if (!emitted && cursor !== null && typeof content === "string") {
      const str = content as string;
      const segEnd = seg.pos + str.length;
      if (cursorPos <= segEnd) {
        const off = cursorPos - seg.pos;
        nodes.push(str.slice(0, off));
        nodes.push(cursor);
        nodes.push(str.slice(off));
        emitted = true;
        continue;
      }
    } else if (!emitted && cursor !== null && cursorPos === seg.pos) {
      nodes.push(cursor);
      emitted = true;
    }
    nodes.push(content);
  }
  if (!emitted && cursor !== null) nodes.push(cursor);
  nodes.push(" ");
  return nodes;
}

const REASONING_OPTIONS = [
  { value: "none", label: "Off" },
  { value: "low", label: "Light" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "Hard" },
] as const;

// ── Project picker ────────────────────────────────────────────────────────────

function ProjectPicker({
  projects,
  value,
  disabled,
  onChange,
}: {
  projects: WorkspaceProject[];
  value: string;
  disabled?: boolean;
  onChange: (slug: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const selected = projects.find((p) => p.slug === value);
  const options = [{ slug: "", name: "No project" }, ...projects];

  useEffect(() => {
    if (!open) return;
    const update = () => {
      if (ref.current) setRect(ref.current.getBoundingClientRect());
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node;
      if (ref.current?.contains(target) || menuRef.current?.contains(target)) return;
      setOpen(false);
    };
    const timer = setTimeout(() => document.addEventListener("mousedown", handler), 0);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("mousedown", handler);
    };
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const selectProject = (slug: string) => {
    setOpen(false);
    if (slug !== value) onChange(slug);
  };

  const menu = open && rect
    ? (() => {
        const menuHeight = Math.min(260, options.length * 32 + 8);
        const openUp = rect.bottom + menuHeight + 8 > window.innerHeight;
        return createPortal(
        <div
          ref={menuRef}
          style={{
            position: "fixed",
            left: rect.left,
            width: Math.max(rect.width, 164),
            ...(openUp
              ? { bottom: window.innerHeight - rect.top + 6 }
              : { top: rect.bottom + 6 }),
          }}
          className="z-[210] overflow-hidden rounded-lg border border-border bg-popover/95 p-1 shadow-xl shadow-black/25 backdrop-blur-xl"
          role="menu"
        >
          {options.map((project) => {
            const isSelected = project.slug === value;
            return (
              <button
                key={project.slug || "__none__"}
                type="button"
                role="menuitemradio"
                aria-checked={isSelected}
                onPointerDown={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  selectProject(project.slug);
                }}
                className={`flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[12px] transition ${
                  isSelected
                    ? "bg-foreground/10 text-foreground"
                    : "text-muted-foreground hover:bg-foreground/7 hover:text-foreground"
                }`}
              >
                <Check className={`h-3.5 w-3.5 shrink-0 ${isSelected ? "text-primary/80" : "opacity-0"}`} />
                <span className="min-w-0 flex-1 truncate">{project.name}</span>
              </button>
            );
          })}
        </div>,
        document.body,
        );
      })()
    : null;

  return (
    <div ref={ref} className="relative min-w-0">
      <button
        type="button"
        aria-label="Project"
        title={selected ? `Project: ${selected.name}` : "No project"}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={`flex h-7 max-w-[190px] items-center gap-1.5 rounded-md border border-transparent px-2 text-[11px] font-medium transition select-none disabled:pointer-events-none disabled:opacity-50 sm:max-w-[230px] ${
          open
            ? "bg-foreground/10 text-foreground"
            : "bg-foreground/[0.045] text-muted-foreground/70 hover:bg-foreground/7 hover:text-foreground"
        }`}
      >
        <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground/45" />
        <span className="min-w-0 truncate text-foreground/90">{selected?.name ?? "No project"}</span>
        <ChevronDown className={`h-3 w-3 shrink-0 opacity-40 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {menu}
    </div>
  );
}

// ── Model dropdown ────────────────────────────────────────────────────────────

function ModelDropdown({
  value,
  suggestions,
  provider,
  label,
  saving,
  onChange,
}: {
  value: string;
  suggestions: string[];
  provider: string;
  label: string;
  saving: boolean;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [rect, setRect] = useState<DOMRect | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  // Build deduplicated list with current value always included
  const allOptions = [value, ...suggestions.filter((s) => s !== value)];
  const filtered = search
    ? allOptions.filter((s) => s.toLowerCase().includes(search.toLowerCase()))
    : allOptions;

  // Track the trigger's viewport position so the portalled menu can be placed
  // with fixed positioning (it lives outside the overflow-hidden popover, so
  // it can never be clipped).
  useEffect(() => {
    if (!open) return;
    const update = () => {
      if (ref.current) setRect(ref.current.getBoundingClientRect());
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (ref.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    const timer = setTimeout(() => document.addEventListener("mousedown", handler), 0);
    return () => { clearTimeout(timer); document.removeEventListener("mousedown", handler); };
  }, [open]);

  useEffect(() => {
    if (open) setTimeout(() => searchRef.current?.focus(), 50);
    else setSearch("");
  }, [open]);

  const select = (v: string) => {
    setOpen(false);
    if (v !== value) onChange(v);
  };

  // Open upward: the composer sits at the bottom of the screen, so anchor the
  // menu's bottom to the trigger's top.
  const menu =
    open && rect
      ? createPortal(
          <div
            ref={menuRef}
            data-model-dropdown-menu="true"
            style={{
              position: "fixed",
              left: rect.left,
              width: rect.width,
              bottom: window.innerHeight - rect.top + 4,
            }}
            className="z-[200] rounded-md border border-border bg-popover shadow-xl overflow-hidden"
          >
            {allOptions.length > 5 && (
              <div className="border-b border-border px-2 py-1.5">
                <input
                  ref={searchRef}
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") setOpen(false);
                    if (e.key === "Enter" && filtered.length === 1) select(filtered[0]);
                  }}
                  placeholder="Search models…"
                  className="w-full bg-transparent text-xs text-foreground placeholder:text-muted-foreground/40 focus:outline-none"
                />
              </div>
            )}
            <div className="max-h-[240px] overflow-y-auto py-1">
              {filtered.length === 0 ? (
                <div className="px-3 py-2 text-xs text-muted-foreground/40">No matches</div>
              ) : (
                filtered.map((opt) => (
                  <button
                    key={opt}
                    type="button"
                    onPointerDown={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      select(opt);
                    }}
                    onClick={(e) => e.stopPropagation()}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-sm text-left transition hover:bg-secondary"
                  >
                    <Check className={`h-3 w-3 shrink-0 ${opt === value ? "text-primary" : "opacity-0"}`} />
                    <span className="truncate">{opt}</span>
                  </button>
                ))
              )}
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <div ref={ref} className="relative">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50">
          {label}
        </span>
        {provider && (
          <span className="text-[10px] text-muted-foreground/35">{provider}</span>
        )}
      </div>

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between rounded-md border border-input bg-background px-2.5 py-1.5 text-sm transition hover:border-border focus:outline-none"
      >
        <span className="truncate">{value || <span className="text-muted-foreground/40">Select model</span>}</span>
        <div className="flex items-center gap-1.5 shrink-0 ml-2">
          {saving && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/50" />}
          <ChevronDown className={`h-3.5 w-3.5 text-muted-foreground/40 transition-transform ${open ? "rotate-180" : ""}`} />
        </div>
      </button>

      {menu}
    </div>
  );
}

// ── Quick-settings popover ────────────────────────────────────────────────────

function ModelQuickSettings({
  status,
  suggestions,
  onClose,
  onStatusChange,
}: {
  status: ModelStatusResponse;
  suggestions: ModelSuggestionsResponse | null;
  onClose: () => void;
  onStatusChange: (s: Partial<ModelStatusResponse>) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [savingSmartModel, setSavingSmartModel] = useState(false);
  const [savingFastModel, setSavingFastModel] = useState(false);
  const [savingReasoning, setSavingReasoning] = useState(false);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        ref.current?.contains(e.target as Node) ||
        target?.closest('[data-model-dropdown-menu="true"]')
      ) {
        return;
      }
      onClose();
    };
    const t = setTimeout(() => document.addEventListener("mousedown", handler), 0);
    return () => { clearTimeout(t); document.removeEventListener("mousedown", handler); };
  }, [onClose]);

  const saveSmartModel = async (model: string) => {
    setSavingSmartModel(true);
    try {
      await api.setSmartModel(model);
      onStatusChange({ smart_model: model });
    } finally {
      setSavingSmartModel(false);
    }
  };

  const saveFastModel = async (model: string) => {
    setSavingFastModel(true);
    try {
      await api.setFastModel(model);
      onStatusChange({ fast_model: model });
    } finally {
      setSavingFastModel(false);
    }
  };

  const setReasoning = async (effort: string) => {
    if (savingReasoning || effort === status.reasoning_effort) return;
    setSavingReasoning(true);
    try {
      await api.setReasoningEffort(effort);
      onStatusChange({ reasoning_effort: effort });
    } finally {
      setSavingReasoning(false);
    }
  };

  return (
    <div
      ref={ref}
      className="absolute bottom-full mb-2 left-0 right-0 mx-3 z-50 rounded-xl border border-border bg-card shadow-xl overflow-hidden"
    >
      <div className="px-3 pt-3 pb-2 space-y-3">

        {/* Smart model */}
        <ModelDropdown
          value={status.smart_model}
          suggestions={suggestions?.smart ?? []}
          provider={status.smart_provider}
          label={status.multi_model_enabled ? "Smart model" : "Model"}
          saving={savingSmartModel}
          onChange={(v) => void saveSmartModel(v)}
        />

        {/* Fast model — only shown when multi-model is enabled */}
        {status.multi_model_enabled && (
          <ModelDropdown
            value={status.fast_model}
            suggestions={suggestions?.fast ?? []}
            provider={status.fast_provider}
            label="Fast model"
            saving={savingFastModel}
            onChange={(v) => void saveFastModel(v)}
          />
        )}

        {/* Reasoning */}
        {status.reasoning_supported && (
          <div>
            <div className="mb-1.5 flex items-center gap-1.5">
              <Brain className="h-3 w-3 text-muted-foreground/40" />
              <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50">
                Reasoning
              </span>
            </div>
            <div className="flex gap-1 flex-wrap">
              {REASONING_OPTIONS.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  disabled={savingReasoning}
                  onClick={() => void setReasoning(value)}
                  className={`rounded-md px-2.5 py-1 text-[11px] font-medium border transition disabled:pointer-events-none ${
                    status.reasoning_effort === value
                      ? "border-primary/50 bg-primary/10 text-primary"
                      : "border-border bg-background text-muted-foreground hover:bg-secondary hover:text-foreground"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-border px-3 py-1.5 flex items-center justify-end">
        <button
          type="button"
          onClick={() => { onClose(); document.dispatchEvent(new CustomEvent("spark:open-settings")); }}
          className="flex items-center gap-1 text-[10px] text-muted-foreground/40 hover:text-muted-foreground transition"
        >
          <Settings className="h-3 w-3" />
          Full settings
        </button>
      </div>
    </div>
  );
}

// ── PromptBar ─────────────────────────────────────────────────────────────────

export function PromptBar({
  input,
  setInput,
  streaming,
  onSend,
  onStop,
  onUploadFiles,
  onAttachPath,
  onRemoveContextItem,
  onUpdateContextMode,
  disabled,
  workspaceSlug,
  contextItems = [],
  sessionId,
  projectOptions,
  selectedProjectSlug,
  onProjectChange,
  placeholder,
}: PromptBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mirrorRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [showMenu, setShowMenu] = useState(false);
  const [showAtMenu, setShowAtMenu] = useState(false);
  const [menuHasItems, setMenuHasItems] = useState(false);
  const [atQuery, setAtQuery] = useState("");
  const [slashTokenStart, setSlashTokenStart] = useState<number>(-1);
  const [slashQuery, setSlashQuery] = useState("");
  const [cursorPos, setCursorPos] = useState(0);
  const [uploading, setUploading] = useState(false);

  const [modelStatus, setModelStatus] = useState<ModelStatusResponse | null>(null);
  const [modelSuggestions, setModelSuggestions] = useState<ModelSuggestionsResponse | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  const [isFocused, setIsFocused] = useState(false);
  const [showHint, setShowHint] = useState(
    () => !localStorage.getItem("spark-prompt-hint-dismissed")
  );

  const { estimate, loading: estimateLoading } = useTokenEstimate(input, contextItems, sessionId);

  useEffect(() => {
    api.getModelStatus().then(setModelStatus).catch(() => {});
    api.getModelSuggestions().then(setModelSuggestions).catch(() => {});
  }, []);

  const handleStatusChange = (patch: Partial<ModelStatusResponse>) => {
    setModelStatus((prev) => prev ? { ...prev, ...patch } : prev);
    // Re-fetch suggestions if the model changed (provider might have changed)
    if (patch.smart_model || patch.fast_model) {
      api.getModelSuggestions().then(setModelSuggestions).catch(() => {});
    }
  };

  const resize = () => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 240) + "px";
  };

  useEffect(resize, [input]);

  const syncScroll = () => {
    if (mirrorRef.current && textareaRef.current) {
      mirrorRef.current.scrollTop = textareaRef.current.scrollTop;
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (showMenu || showAtMenu) {
      if (["ArrowUp", "ArrowDown", "Escape"].includes(e.key)) return;
      if (e.key === "Tab") { e.preventDefault(); return; }
      if (e.key === "Enter" && !e.shiftKey && (menuHasItems || showAtMenu)) { e.preventDefault(); return; }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
    if (e.key === "Escape") {
      setShowMenu(false);
      setShowAtMenu(false);
      setShowSettings(false);
    }
  };

  const handleSend = () => {
    if (showHint) {
      setShowHint(false);
      localStorage.setItem("spark-prompt-hint-dismissed", "1");
    }
    onSend();
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    const cursor = e.target.selectionStart ?? val.length;
    setInput(val);
    setCursorPos(cursor);
    const beforeCursor = val.slice(0, cursor);
    const slashMatch = /(^|\s)(\/\S*)$/.exec(beforeCursor);
    if (slashMatch) {
      const token = slashMatch[2];
      setSlashQuery(token.slice(1));
      setSlashTokenStart(cursor - token.length);
      setShowMenu(true);
    } else {
      setShowMenu(false);
      setSlashTokenStart(-1);
      setSlashQuery("");
    }
    const atMatch = /(@\S*)$/.exec(beforeCursor);
    if (atMatch) {
      setAtQuery(atMatch[1].slice(1));
      setShowAtMenu(true);
    } else {
      setShowAtMenu(false);
    }
  };

  const handleSlashSelect = (command: string) => {
    const textarea = textareaRef.current;
    const insertToken = `/${command} `;
    if (slashTokenStart >= 0) {
      const tokenEnd = slashTokenStart + 1 + slashQuery.length;
      const newInput = input.slice(0, slashTokenStart) + insertToken + input.slice(tokenEnd);
      setInput(newInput);
      setTimeout(() => {
        const pos = slashTokenStart + insertToken.length;
        if (textarea) { textarea.selectionStart = textarea.selectionEnd = pos; textarea.focus(); }
      }, 0);
    } else {
      setInput(insertToken);
      setTimeout(() => textarea?.focus(), 0);
    }
    setShowMenu(false);
    setMenuHasItems(false);
    setSlashTokenStart(-1);
    setSlashQuery("");
  };

  const handleAtSelect = (path: string, isDir: boolean) => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    const cursor = textarea.selectionStart ?? input.length;
    const beforeCursor = input.slice(0, cursor);
    const atMatch = /(@\S*)$/.exec(beforeCursor);
    if (!atMatch) return;
    const atStart = cursor - atMatch[0].length;

    if (!isDir && onAttachPath) {
      const newToken = `@${path} `;
      const newInput = input.slice(0, atStart) + newToken + input.slice(cursor);
      setInput(newInput);
      setShowAtMenu(false);
      onAttachPath(path);
      setTimeout(() => {
        const pos = atStart + newToken.length;
        textarea.selectionStart = textarea.selectionEnd = pos;
        textarea.focus();
      }, 0);
      return;
    }

    const newToken = `@${path}${isDir ? "/" : " "}`;
    const newInput = input.slice(0, atStart) + newToken + input.slice(cursor);
    setInput(newInput);
    if (isDir) {
      setAtQuery(`${path}/`);
    } else {
      setShowAtMenu(false);
    }
    setTimeout(() => {
      const pos = atStart + newToken.length;
      textarea.selectionStart = textarea.selectionEnd = pos;
      textarea.focus();
    }, 0);
  };

  const handleFilesSelected = async (files: FileList | null) => {
    if (!files || !onUploadFiles) return;
    const arr = Array.from(files);
    if (!arr.length) return;
    setUploading(true);
    try {
      await onUploadFiles(arr);
      textareaRef.current?.focus();
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const blocked = disabled || streaming || uploading;
  // The textarea stays editable while streaming so the user can type a redirect
  // ("actually, do X instead") that interrupts the running turn on Enter.
  const inputBlocked = disabled || uploading;
  const canSend = !!input.trim() && !blocked;
  const canRedirect = !!input.trim() && streaming && !disabled && !uploading;

  const activeModel = modelStatus
    ? (modelStatus.multi_model_enabled && modelStatus.fast_model) || modelStatus.smart_model || null
    : null;
  const modelLabel = activeModel ? shortModelName(activeModel) : null;
  const effortLabel = (() => {
    const e = modelStatus?.reasoning_effort;
    if (!e || e === "none") return null;
    return REASONING_OPTIONS.find((o) => o.value === e)?.label ?? e;
  })();
  const showProjectPicker = projectOptions !== undefined && selectedProjectSlug !== undefined && !!onProjectChange;

  return (
    <div className="px-3 pb-3 pt-2 shrink-0 relative">
      {showMenu && (
        <SlashCommandMenu
          query={slashQuery}
          onSelect={handleSlashSelect}
          onClose={() => setShowMenu(false)}
          onItemCountChange={(count) => setMenuHasItems(count > 0)}
        />
      )}
      {showAtMenu && (
        <AtFileMenu
          query={atQuery}
          workspaceSlug={workspaceSlug}
          onSelect={handleAtSelect}
          onClose={() => setShowAtMenu(false)}
        />
      )}

      {showSettings && modelStatus && (
        <ModelQuickSettings
          status={modelStatus}
          suggestions={modelSuggestions}
          onClose={() => setShowSettings(false)}
          onStatusChange={handleStatusChange}
        />
      )}

      {/* Unified card — no focus ring */}
      <div className={`rounded-lg border border-input bg-card/58 shadow-lg shadow-black/10 backdrop-blur-xl ${inputBlocked ? "opacity-60" : ""}`}>
        {/* Textarea */}
        <div className="relative min-h-[52px]">
          <div
            ref={mirrorRef}
            aria-hidden
            className="absolute inset-0 pointer-events-none overflow-hidden px-4 pt-3.5 pb-2 text-sm text-foreground whitespace-pre-wrap break-words select-none"
          >
            {renderMirror(input, cursorPos, isFocused)}
          </div>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onKeyUp={(e) => setCursorPos(e.currentTarget.selectionStart ?? 0)}
            onClick={(e) => setCursorPos(e.currentTarget.selectionStart ?? 0)}
            onSelect={(e) => setCursorPos(e.currentTarget.selectionStart ?? 0)}
            onScroll={syncScroll}
            onFocus={(e) => { setIsFocused(true); setCursorPos(e.currentTarget.selectionStart ?? 0); }}
            onBlur={() => setIsFocused(false)}
            disabled={inputBlocked}
            placeholder={
              isFocused ? "" : streaming ? "Type to redirect · Enter to send while responding" : uploading ? "Uploading…" : placeholder ?? "Ask anything · / for commands · @ for context"
            }
            rows={1}
            className="relative z-10 w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-sm placeholder:text-muted-foreground/50 focus:outline-none disabled:cursor-not-allowed min-h-[52px] max-h-[240px] overflow-y-auto"
            style={{ height: "52px", color: "transparent", caretColor: "transparent" }}
          />
        </div>

        {/* Toolbar */}
        <div className="flex items-center gap-1 px-2 pb-2 pt-0">
          {/* Attach */}
          {onUploadFiles && (
            <>
              <button
                type="button"
                disabled={blocked}
                onClick={() => fileInputRef.current?.click()}
                title="Add file"
                className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground/55 transition hover:bg-foreground/7 hover:text-foreground disabled:pointer-events-none"
              >
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => void handleFilesSelected(e.target.files)}
              />
            </>
          )}

          {/* Model + reasoning pill */}
          {modelLabel && (
            <button
              type="button"
              onClick={() => setShowSettings((v) => !v)}
              title="Quick model settings"
              className={`flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition select-none ${
                showSettings
                  ? "bg-foreground/8 text-foreground"
                  : "text-muted-foreground/60 hover:bg-foreground/7 hover:text-foreground"
              }`}
            >
              <span>{modelLabel}</span>
              {effortLabel && modelStatus?.reasoning_supported && (
                <>
                  <span className="text-muted-foreground/30">·</span>
                  <Brain className="h-3 w-3 text-primary/60" />
                  <span className="text-primary/70">{effortLabel}</span>
                </>
              )}
              <ChevronDown className={`h-3 w-3 opacity-40 transition-transform ${showSettings ? "rotate-180" : ""}`} />
            </button>
          )}

          {showProjectPicker && (
            <ProjectPicker
              projects={projectOptions}
              value={selectedProjectSlug}
              disabled={inputBlocked}
              onChange={onProjectChange}
            />
          )}

          <div className="flex-1" />

          {/* Token budget indicator */}
          <TokenBudgetIndicator
            estimate={estimate}
            loading={estimateLoading}
            contextItems={contextItems}
            onRemoveItem={onRemoveContextItem}
            onUpdateMode={onUpdateContextMode}
          />

          {/* Keyboard hint */}
          {showHint && !streaming && (
            <span className="hidden sm:flex items-center gap-0.5 text-[10px] text-muted-foreground/30 select-none mr-1">
              <kbd className="font-sans">⏎</kbd>
              <span>to send</span>
            </span>
          )}

          {/* Send / Redirect / Stop */}
          {streaming ? (
            <div className="flex items-center gap-1">
              {canRedirect && (
                <button
                  type="button"
                  onClick={handleSend}
                  title="Redirect (interrupt with this message)"
                  className="flex h-7 w-7 items-center justify-center rounded-md bg-foreground text-background transition hover:bg-foreground/90"
                >
                  <ArrowUp className="h-4 w-4" />
                </button>
              )}
              <button
                type="button"
                onClick={onStop}
                title="Stop"
                className="flex h-7 w-7 items-center justify-center rounded-md bg-destructive text-destructive-foreground transition hover:bg-destructive/90"
              >
                <Square className="h-3.5 w-3.5" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              disabled={!canSend}
              onClick={handleSend}
              title="Send (Enter)"
              className="flex h-7 w-7 items-center justify-center rounded-md bg-foreground text-background transition hover:bg-foreground/90 disabled:opacity-30 disabled:pointer-events-none"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
