import { useEffect, useState } from "react";
import { Zap, AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";

interface UsageWindow {
  label: string;
  used_percent: number;
  reset_at?: number;
  reset_after_seconds?: number;
  window_seconds?: number;
}

interface CodexUsageResponse {
  available: boolean;
  reason?: string;
  provider_connected?: boolean;
  active_model?: string;
  plan_type?: string;
  limit_reached?: boolean;
  windows?: UsageWindow[];
}

function formatReset(reset_at?: number, reset_after_seconds?: number): string {
  const secsLeft = reset_after_seconds ?? (reset_at ? reset_at - Date.now() / 1000 : 0);
  if (secsLeft <= 0) return "";
  if (secsLeft < 3600) return `${Math.ceil(secsLeft / 60)}m`;
  if (secsLeft < 86400) {
    const d = reset_at ? new Date(reset_at * 1000) : null;
    return d ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : `${Math.ceil(secsLeft / 3600)}h`;
  }
  const d = reset_at ? new Date(reset_at * 1000) : null;
  return d ? d.toLocaleDateString([], { month: "short", day: "numeric" }) : "";
}

function UsageBar({ window: w }: { window: UsageWindow }) {
  const pctUsed = Math.max(0, Math.min(100, w.used_percent));
  const pctRemaining = 100 - pctUsed;
  const isLow = pctRemaining <= 25;
  const isEmpty = pctRemaining <= 5;
  const barColor = isEmpty ? "bg-destructive/80" : isLow ? "bg-amber-400/90" : "bg-emerald-500/90";
  const textColor = isEmpty ? "text-destructive" : isLow ? "text-amber-400" : "text-emerald-400";
  const resetLabel = formatReset(w.reset_at, w.reset_after_seconds);

  return (
    <div className="group relative flex flex-col gap-1 min-w-[68px]">
      <div className="flex items-center justify-between gap-1">
        <span className="text-[9px] font-medium tracking-[0.04em] text-muted-foreground truncate leading-none">
          {w.label}
        </span>
        <span className={`text-[9px] font-semibold leading-none tabular-nums ${textColor}`}>
          {Math.round(pctUsed)}% Used
        </span>
      </div>
      <div className="h-[3px] w-full rounded-full bg-white/10 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ${barColor}`}
          style={{ width: `${pctUsed}%` }}
        />
      </div>
      {resetLabel && (
        <div className="pointer-events-none absolute -bottom-5 left-0 z-50 hidden group-hover:block whitespace-nowrap rounded border border-border bg-popover px-1.5 py-0.5 text-[10px] text-muted-foreground shadow-lg">
          Resets {resetLabel}
        </div>
      )}
    </div>
  );
}

export function CodexUsageBadge() {
  const [data, setData] = useState<CodexUsageResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function fetch() {
      try {
        const resp = await api.getCodexUsage();
        if (!cancelled) setData(resp as CodexUsageResponse);
      } catch {
        if (!cancelled) setData(null);
      }
    }
    fetch();
    const t = setInterval(fetch, 60_000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  if (!data?.available || !data.provider_connected) return null;

  const windows = data.windows ?? [];
  const limitReached = data.limit_reached;

  // Limit reached warning
  if (limitReached && windows.length > 0) {
    const nextReset = windows
      .map((w) => w.reset_after_seconds ?? 0)
      .filter(Boolean)
      .sort()[0];
    const resetLabel = nextReset ? formatReset(undefined, nextReset) : "";
    return (
      <div className="hidden items-center gap-1.5 md:flex px-2 py-1 rounded-sm border border-amber-500/40 bg-amber-500/10">
        <AlertTriangle className="h-3 w-3 text-amber-400 shrink-0" />
        <span className="text-[10px] font-medium text-amber-300">
          Limit reached{resetLabel ? ` · resets in ${resetLabel}` : ""}
        </span>
      </div>
    );
  }

  // Real usage windows from wham/usage
  if (windows.length > 0) {
    return (
      <div className="hidden items-center gap-3 md:flex px-2 py-1.5 rounded-sm border border-border/50 bg-card/40">
        {windows.map((w) => (
          <UsageBar key={w.label} window={w} />
        ))}
      </div>
    );
  }

  // Fallback: just show active model as a connected pill
  const modelLabel = data.active_model || "Codex";
  return (
    <div
      className="hidden items-center gap-1.5 md:flex px-2 py-1 rounded-sm border border-primary/20 bg-primary/5"
      title="OpenAI Codex connected"
    >
      <Zap className="h-3 w-3 text-primary/60 shrink-0" />
      <span className="text-[10px] font-medium text-primary/70 uppercase tracking-[0.1em]">
        {modelLabel}
      </span>
    </div>
  );
}
