import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

export interface SessionStats {
  model?: string | null;
  inputTokens?: number;
  outputTokens?: number;
  cacheReadTokens?: number;
  costUsd?: number;
  turnCount?: number;
}

function fmt(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function fmtCost(n: number): string {
  if (n < 0.001) return "<$0.001";
  return `$${n.toFixed(3)}`;
}

export function SessionInfoBar({ stats }: { stats: SessionStats }) {
  const [expanded, setExpanded] = useState(false);

  const hasData = stats.model || stats.inputTokens || stats.turnCount;
  if (!hasData) return null;

  return (
    <div className="border-t border-border/40 bg-muted/10 px-4 py-1 shrink-0">
      <button
        type="button"
        className="w-full flex items-center gap-3 text-[10px] text-muted-foreground/70 hover:text-muted-foreground transition-colors"
        onClick={() => setExpanded((p) => !p)}
        title={expanded ? "Collapse stats" : "Expand stats"}
      >
        {stats.model && (
          <span className="font-mono text-primary/60 truncate max-w-[140px]">{stats.model}</span>
        )}
        {stats.inputTokens != null && stats.inputTokens > 0 && (
          <span title="Input tokens">↑ {fmt(stats.inputTokens)}</span>
        )}
        {stats.outputTokens != null && stats.outputTokens > 0 && (
          <span title="Output tokens">↓ {fmt(stats.outputTokens)}</span>
        )}
        {stats.cacheReadTokens != null && stats.cacheReadTokens > 0 && (
          <span title="Cache read tokens" className="text-success/60">💾 {fmt(stats.cacheReadTokens)}</span>
        )}
        {stats.costUsd != null && stats.costUsd > 0 && (
          <span title="Estimated cost">~{fmtCost(stats.costUsd)}</span>
        )}
        {stats.turnCount != null && stats.turnCount > 0 && (
          <span title="Turns" className="ml-auto">{stats.turnCount} {stats.turnCount === 1 ? "turn" : "turns"}</span>
        )}
        <span className="shrink-0 ml-0.5">{expanded ? <ChevronDown className="h-2.5 w-2.5" /> : <ChevronUp className="h-2.5 w-2.5" />}</span>
      </button>

      {expanded && (
        <div className="mt-1 pb-1 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px] text-muted-foreground/60">
          {stats.model && (
            <><span>Model</span><span className="font-mono text-primary/60 truncate">{stats.model}</span></>
          )}
          {stats.inputTokens != null && stats.inputTokens > 0 && (
            <><span>Input tokens</span><span>{stats.inputTokens.toLocaleString()}</span></>
          )}
          {stats.outputTokens != null && stats.outputTokens > 0 && (
            <><span>Output tokens</span><span>{stats.outputTokens.toLocaleString()}</span></>
          )}
          {stats.cacheReadTokens != null && stats.cacheReadTokens > 0 && (
            <><span>Cached</span><span className="text-success/70">{stats.cacheReadTokens.toLocaleString()}</span></>
          )}
          {stats.costUsd != null && stats.costUsd > 0 && (
            <><span>Est. cost</span><span>{fmtCost(stats.costUsd)}</span></>
          )}
          {stats.turnCount != null && (
            <><span>Turns</span><span>{stats.turnCount}</span></>
          )}
        </div>
      )}
    </div>
  );
}
