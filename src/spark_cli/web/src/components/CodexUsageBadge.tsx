import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface UsageLimitEntry {
  label?: string;
  remaining?: number;        // 0–100 percentage remaining
  reset_at?: string;         // ISO timestamp or human-readable string
  human_readable_reset_time?: string;
  is_limited?: boolean;
  level?: string;
  pct_remaining?: number;
}

interface CodexUsageData {
  usage?: UsageLimitEntry[];
  // flat format some endpoints return
  five_hour?: { pct_remaining?: number; reset_at?: string; limited?: boolean };
  weekly?: { pct_remaining?: number; reset_at?: string; limited?: boolean };
}

interface NormalizedLimit {
  label: string;
  pctRemaining: number;
  resetLabel: string;
  limited: boolean;
}

function normalizeUsageData(raw: CodexUsageData): NormalizedLimit[] {
  const limits: NormalizedLimit[] = [];

  // Array-style response
  if (Array.isArray(raw?.usage)) {
    for (const entry of raw.usage) {
      const pct = entry.pct_remaining ?? entry.remaining ?? 100;
      const reset = entry.human_readable_reset_time ?? formatResetAt(entry.reset_at);
      limits.push({
        label: entry.label ?? "Usage limit",
        pctRemaining: pct,
        resetLabel: reset,
        limited: !!entry.is_limited,
      });
    }
    return limits;
  }

  // Flat-style response
  if (raw?.five_hour) {
    limits.push({
      label: "5 hour limit",
      pctRemaining: raw.five_hour.pct_remaining ?? 100,
      resetLabel: formatResetAt(raw.five_hour.reset_at),
      limited: !!raw.five_hour.limited,
    });
  }
  if (raw?.weekly) {
    limits.push({
      label: "Weekly limit",
      pctRemaining: raw.weekly.pct_remaining ?? 100,
      resetLabel: formatResetAt(raw.weekly.reset_at),
      limited: !!raw.weekly.limited,
    });
  }

  return limits;
}

function formatResetAt(resetAt?: string): string {
  if (!resetAt) return "";
  // If it's already a human-readable string (not ISO), return as-is
  if (!/^\d{4}-/.test(resetAt)) return resetAt;
  try {
    const d = new Date(resetAt);
    const now = new Date();
    const diffMs = d.getTime() - now.getTime();
    if (diffMs < 0) return "";
    const diffH = diffMs / 3600000;
    if (diffH < 24) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  } catch {
    return resetAt;
  }
}

function UsagePill({ limit }: { limit: NormalizedLimit }) {
  const pct = Math.max(0, Math.min(100, limit.pctRemaining));
  const isEmpty = pct <= 5;
  const isLow = pct <= 25;

  const barColor = isEmpty || limit.limited
    ? "bg-destructive/80"
    : isLow
    ? "bg-amber-400/90"
    : "bg-emerald-500/90";

  return (
    <div className="group relative flex flex-col gap-0.5 min-w-[72px]">
      <div className="flex items-center justify-between gap-1">
        <span className="text-[9px] font-medium uppercase tracking-[0.1em] text-muted-foreground truncate leading-none">
          {limit.label}
        </span>
        <span
          className={`text-[9px] font-semibold leading-none tabular-nums ${
            isEmpty || limit.limited ? "text-destructive" : isLow ? "text-amber-400" : "text-emerald-400"
          }`}
        >
          {Math.round(pct)}%
        </span>
      </div>
      <div className="h-[3px] w-full rounded-full bg-white/10 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      {limit.resetLabel && (
        <div className="pointer-events-none absolute -bottom-5 left-0 z-50 hidden group-hover:block whitespace-nowrap rounded border border-border bg-popover px-1.5 py-0.5 text-[10px] text-muted-foreground shadow-lg">
          Resets {limit.resetLabel}
        </div>
      )}
    </div>
  );
}

export function CodexUsageBadge() {
  const [limits, setLimits] = useState<NormalizedLimit[]>([]);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function fetchUsage() {
      try {
        const resp = await api.getCodexUsage();
        if (cancelled) return;
        if (!resp.available || !resp.data) {
          setVisible(false);
          return;
        }
        const normalized = normalizeUsageData(resp.data as CodexUsageData);
        if (normalized.length === 0) {
          setVisible(false);
          return;
        }
        setLimits(normalized);
        setVisible(true);
      } catch {
        if (!cancelled) setVisible(false);
      }
    }

    fetchUsage();
    const interval = setInterval(fetchUsage, 60_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (!visible || limits.length === 0) return null;

  return (
    <div className="hidden items-center gap-3 md:flex px-2 py-1 rounded-sm border border-border/50 bg-card/50">
      {limits.map((limit) => (
        <UsagePill key={limit.label} limit={limit} />
      ))}
    </div>
  );
}
