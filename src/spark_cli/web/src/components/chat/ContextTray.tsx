import { memo, useState } from "react";
import { AlertTriangle, File, FileText, Globe, Hammer, Minus, Pin, PinOff, X, ChevronDown, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ContextItem, InclusionMode, ContextScope } from "@/lib/context";

interface ContextTrayProps {
  items: ContextItem[];
  onRemove: (id: string) => void;
  onUpdateMode: (id: string, mode: InclusionMode) => void;
  onUpdateScope: (id: string, scope: ContextScope) => void;
  onUpdateItem?: (id: string, patch: Partial<ContextItem>) => void;
  onSummarize?: (id: string) => void;
  className?: string;
}

const MODE_LABELS: Record<InclusionMode, string> = {
  path_only: "Path",
  excerpt: "Excerpt",
  summary: "Summary",
  full: "Full",
  search: "Search",
  diff: "Diff",
};

const MODE_ORDER: InclusionMode[] = ["path_only", "excerpt", "summary", "full", "search", "diff"];

function itemIcon(type: ContextItem["type"]) {
  switch (type) {
    case "file":
    case "excerpt":
      return <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />;
    case "note":
      return <Minus className="h-3 w-3 shrink-0 text-muted-foreground" />;
    case "tool_output":
      return <Hammer className="h-3 w-3 shrink-0 text-muted-foreground" />;
    case "url":
      return <Globe className="h-3 w-3 shrink-0 text-muted-foreground" />;
    default:
      return <File className="h-3 w-3 shrink-0 text-muted-foreground" />;
  }
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return "";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

const ContextTrayItem = memo(function ContextTrayItem({
  item,
  onRemove,
  onUpdateMode,
  onUpdateScope,
  onUpdateItem,
  onSummarize,
}: {
  item: ContextItem;
  onRemove: (id: string) => void;
  onUpdateMode: (id: string, mode: InclusionMode) => void;
  onUpdateScope: (id: string, scope: ContextScope) => void;
  onUpdateItem?: (id: string, patch: Partial<ContextItem>) => void;
  onSummarize?: (id: string) => void;
}) {
  const [modeOpen, setModeOpen] = useState(false);
  const [excerptInput, setExcerptInput] = useState(
    item.excerpt_range ? `${item.excerpt_range[0]}-${item.excerpt_range[1]}` : ""
  );
  const [searchInput, setSearchInput] = useState(item.search_query ?? "");
  const displayName = item.label ?? item.source_path?.split("/").pop() ?? item.id;
  const isPinned = item.scope === "pinned";
  const sizeLabel = item.inclusion_mode !== "path_only" ? formatBytes(item.size_bytes) : "";
  const isLargeFullContent = item.inclusion_mode === "full" && item.size_bytes > 100 * 1024;

  return (
    <div className={cn(
      "group flex items-center gap-1.5 rounded-md border bg-secondary/40 px-2 py-1 text-xs relative",
      isLargeFullContent ? "border-warning/50" : "border-border/50",
    )}>
      {itemIcon(item.type)}

      <span className="truncate max-w-[120px] font-mono text-[11px] text-foreground/80" title={item.source_path ?? item.label ?? ""}>
        {displayName}
      </span>

      {sizeLabel && (
        <span className="text-[9px] text-muted-foreground/50 shrink-0">{sizeLabel}</span>
      )}

      {isLargeFullContent && (
        <span title="Large file in full mode — consider switching to summary or excerpt">
          <AlertTriangle className="h-3 w-3 shrink-0 text-warning" />
        </span>
      )}

      {/* Inclusion mode selector */}
      <div className="relative shrink-0">
        <button
          type="button"
          onClick={() => setModeOpen((v) => !v)}
          className="flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] font-medium text-primary/70 hover:bg-primary/10 transition"
        >
          {MODE_LABELS[item.inclusion_mode]}
          <ChevronDown className={`h-2.5 w-2.5 transition-transform ${modeOpen ? "rotate-180" : ""}`} />
        </button>
        {modeOpen && (
          <div className="absolute bottom-full mb-1 left-0 z-50 rounded-md border border-border bg-popover shadow-lg py-1 min-w-[90px]">
            {MODE_ORDER.map((mode) => (
              <button
                key={mode}
                type="button"
                className={cn(
                  "w-full px-2.5 py-1 text-left text-[11px] hover:bg-secondary transition",
                  mode === item.inclusion_mode ? "text-primary font-medium" : "text-foreground/70",
                )}
                onClick={() => {
                  onUpdateMode(item.id, mode);
                  setModeOpen(false);
                }}
              >
                {MODE_LABELS[mode]}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Excerpt range input */}
      {item.inclusion_mode === "excerpt" && onUpdateItem && (
        <input
          type="text"
          value={excerptInput}
          onChange={(e) => setExcerptInput(e.target.value)}
          onBlur={() => {
            const match = excerptInput.match(/^(\d+)-(\d+)$/);
            if (match) {
              onUpdateItem(item.id, { excerpt_range: [parseInt(match[1]), parseInt(match[2])] });
            }
          }}
          placeholder="1-50"
          className="w-14 rounded border border-border/50 bg-background px-1 text-[10px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
          title="Line range (e.g. 1-50)"
        />
      )}

      {/* Search query input */}
      {item.inclusion_mode === "search" && onUpdateItem && (
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onBlur={() => onUpdateItem(item.id, { search_query: searchInput })}
          placeholder="search…"
          className="w-20 rounded border border-border/50 bg-background px-1 text-[10px] text-foreground focus:outline-none focus:ring-1 focus:ring-primary/40"
          title="Search query for bounded snippet extraction"
        />
      )}

      {/* Summarize action (file items only) */}
      {onSummarize && item.type === "file" && item.inclusion_mode !== "summary" && (
        <button
          type="button"
          title="Summarize this file"
          onClick={() => onSummarize(item.id)}
          className="shrink-0 rounded p-0.5 text-muted-foreground/40 hover:text-primary transition opacity-0 group-hover:opacity-100"
        >
          <Sparkles className="h-3 w-3" />
        </button>
      )}

      {/* Pin toggle */}
      <button
        type="button"
        title={isPinned ? "Unpin (one-turn only)" : "Pin across turns"}
        onClick={() => onUpdateScope(item.id, isPinned ? "one_turn" : "pinned")}
        className={cn(
          "shrink-0 rounded p-0.5 transition",
          isPinned
            ? "text-primary hover:text-primary/70"
            : "text-muted-foreground/40 hover:text-foreground opacity-0 group-hover:opacity-100",
        )}
      >
        {isPinned ? <Pin className="h-3 w-3" /> : <PinOff className="h-3 w-3" />}
      </button>

      {/* Remove */}
      <button
        type="button"
        title="Remove"
        onClick={() => onRemove(item.id)}
        className="shrink-0 rounded p-0.5 text-muted-foreground/40 hover:text-destructive transition opacity-0 group-hover:opacity-100"
      >
        <X className="h-3 w-3" />
      </button>
    </div>
  );
});

export const ContextTray = memo(function ContextTray({
  items,
  onRemove,
  onUpdateMode,
  onUpdateScope,
  onUpdateItem,
  onSummarize,
  className,
}: ContextTrayProps) {
  if (items.length === 0) return null;

  return (
    <div className={cn("flex flex-wrap gap-1.5 px-3 pt-1.5 pb-0", className)}>
      {items.map((item) => (
        <ContextTrayItem
          key={item.id}
          item={item}
          onRemove={onRemove}
          onUpdateMode={onUpdateMode}
          onUpdateScope={onUpdateScope}
          onUpdateItem={onUpdateItem}
          onSummarize={onSummarize}
        />
      ))}
    </div>
  );
});
