import { useState } from "react";
import { Loader2, Pin } from "lucide-react";
import type { ContextEstimate, ContextItem, InclusionMode } from "@/lib/context";
import { contextModeSummary, contextPressureLevel, formatContextTokens } from "./contextWindowPolicy";

export interface ContextWindowMeterProps {
  estimate: ContextEstimate | null;
  loading: boolean;
  contextItems?: ContextItem[];
  onRemoveItem?: (id: string) => void;
  onUpdateMode?: (id: string, mode: InclusionMode) => void;
}

function itemLabel(item: ContextItem): string {
  return item.label ?? item.source_path?.split("/").pop() ?? item.id;
}

export function ContextWindowMeter({
  estimate,
  loading,
  contextItems = [],
  onRemoveItem,
  onUpdateMode,
}: ContextWindowMeterProps) {
  const [expanded, setExpanded] = useState(false);

  if (loading && !estimate) {
    return <Loader2 aria-label="Estimating context" className="h-3 w-3 animate-spin text-muted-foreground/40" />;
  }
  if (!estimate) return null;

  const pressure = contextPressureLevel(estimate.utilization);
  const colorClass = pressure === "critical"
    ? "text-destructive"
    : pressure === "warning"
      ? "text-yellow-500"
      : "text-muted-foreground/55";
  const actionableItems = contextItems.filter((item) => (
    item.type === "file" && item.inclusion_mode === "full" && item.scope !== "pinned"
  ));
  const modeSummary = contextModeSummary(contextItems);

  return (
    <div className="relative">
      <button
        type="button"
        aria-haspopup="dialog"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
        title="Estimated context window usage"
        className={`rounded px-1.5 py-1 text-[10px] tabular-nums transition hover:bg-foreground/6 ${colorClass}`}
      >
        Est. {formatContextTokens(estimate.total_tokens)} / {formatContextTokens(estimate.context_window)}
      </button>
      {expanded && (
        <div
          role="dialog"
          aria-label="Estimated context window"
          className="absolute bottom-full right-0 z-50 mb-2 w-72 rounded-xl border border-border bg-popover/95 p-3 text-[11px] shadow-xl backdrop-blur-xl"
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <div>
              <div className="font-medium text-foreground">Estimated context</div>
              <div className="text-[10px] text-muted-foreground">Provider-reported usage appears after the turn.</div>
            </div>
            <span className={`tabular-nums ${colorClass}`}>{Math.round(estimate.utilization * 100)}%</span>
          </div>

          <div className="space-y-1">
            {estimate.buckets.map((bucket) => (
              <div key={bucket.label} className="flex justify-between text-muted-foreground">
                <span>{bucket.label}</span>
                <span className="tabular-nums">{formatContextTokens(bucket.tokens)}</span>
              </div>
            ))}
          </div>

          {modeSummary.length > 0 && (
            <div className="mt-2 rounded-md bg-foreground/5 px-2 py-1 text-muted-foreground">
              Included as {modeSummary.join(" · ")}. Pinned context is preserved.
            </div>
          )}

          {estimate.warning && (
            <div className={`mt-2 rounded-md px-2 py-1.5 ${
              estimate.warning === "limit_exceeded"
                ? "bg-destructive/10 text-destructive"
                : "bg-yellow-500/10 text-yellow-600 dark:text-yellow-400"
            }`}>
              {estimate.warning === "limit_exceeded"
                ? "Context is likely to exceed the model limit. Reduce an item before sending."
                : "Context pressure is high. Spark warns before compaction and only compacts when needed to continue."}
            </div>
          )}

          {actionableItems.length > 0 && (
            <div className="mt-2 space-y-1 border-t border-border pt-2">
              <div className="text-muted-foreground">Reduce attached context</div>
              {actionableItems.map((item) => (
                <div key={item.id} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-muted-foreground" title={itemLabel(item)}>
                    {itemLabel(item)}
                  </span>
                  {onUpdateMode && (
                    <button
                      type="button"
                      onClick={() => onUpdateMode(item.id, "summary")}
                      className="rounded bg-secondary px-1.5 py-0.5 text-foreground hover:bg-secondary/80"
                    >
                      Summarize
                    </button>
                  )}
                  {onRemoveItem && (
                    <button
                      type="button"
                      onClick={() => onRemoveItem(item.id)}
                      className="rounded px-1.5 py-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
                    >
                      Remove
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {contextItems.some((item) => item.scope === "pinned") && (
            <div className="mt-2 flex items-center gap-1 text-[10px] text-muted-foreground">
              <Pin className="h-3 w-3" /> Pinned items and recorded decisions are not silently dropped.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
