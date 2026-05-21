import { useEffect, useState } from "react";
import { Zap, AlertTriangle } from "lucide-react";
import { api } from "@/lib/api";

interface RateLimitBucket {
  limit: number;
  remaining: number;
  reset_seconds: number;
}

interface CodexUsageResponse {
  available: boolean;
  reason?: string;
  provider_connected?: boolean;
  limit_hit?: {
    hit_age_seconds: number;
    resets_at?: number;
    resets_in_seconds?: number;
  } | null;
  rate_limit?: {
    requests_min: RateLimitBucket;
    requests_hour: RateLimitBucket;
    captured_age_seconds: number;
  } | null;
}

function formatResetTime(resets_at?: number, resets_in_seconds?: number): string {
  if (resets_at) {
    const d = new Date(resets_at * 1000);
    const diffH = (resets_at * 1000 - Date.now()) / 3600000;
    if (diffH < 24) {
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }
  if (resets_in_seconds) {
    const h = Math.ceil(resets_in_seconds / 3600);
    return `~${h}h`;
  }
  return "";
}

function RateLimitBar({ label, bucket }: { label: string; bucket: RateLimitBucket }) {
  if (!bucket.limit) return null;
  const pct = Math.max(0, Math.min(100, (bucket.remaining / bucket.limit) * 100));
  const isLow = pct <= 25;
  const isEmpty = pct <= 5;
  const barColor = isEmpty ? "bg-destructive/80" : isLow ? "bg-amber-400/90" : "bg-emerald-500/90";

  return (
    <div className="flex flex-col gap-0.5 min-w-[64px]">
      <div className="flex items-center justify-between gap-1">
        <span className="text-[9px] font-medium uppercase tracking-[0.1em] text-muted-foreground truncate leading-none">
          {label}
        </span>
        <span className={`text-[9px] font-semibold leading-none tabular-nums ${isEmpty ? "text-destructive" : isLow ? "text-amber-400" : "text-emerald-400"}`}>
          {Math.round(pct)}%
        </span>
      </div>
      <div className="h-[3px] w-full rounded-full bg-white/10 overflow-hidden">
        <div className={`h-full rounded-full transition-all duration-500 ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function CodexUsageBadge() {
  const [data, setData] = useState<CodexUsageResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchUsage() {
      try {
        const resp = await api.getCodexUsage();
        if (!cancelled) setData(resp as CodexUsageResponse);
      } catch {
        if (!cancelled) setData(null);
      }
    }

    fetchUsage();
    const interval = setInterval(fetchUsage, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  // Don't render if not a Codex provider or not authenticated
  if (!data?.available || !data.provider_connected) return null;

  const limitHit = data.limit_hit;
  const rateLimitRPM = data.rate_limit?.requests_min;
  const rateLimitRPH = data.rate_limit?.requests_hour;
  const hasRateData = rateLimitRPM?.limit || rateLimitRPH?.limit;

  // Usage limit was hit — show warning with reset time
  if (limitHit) {
    const resetLabel = formatResetTime(limitHit.resets_at ?? undefined, limitHit.resets_in_seconds ?? undefined);
    return (
      <div className="hidden items-center gap-1.5 md:flex px-2 py-1 rounded-sm border border-amber-500/40 bg-amber-500/10">
        <AlertTriangle className="h-3 w-3 text-amber-400 shrink-0" />
        <span className="text-[10px] font-medium text-amber-300">
          Usage limit{resetLabel ? ` · resets ${resetLabel}` : ""}
        </span>
      </div>
    );
  }

  // Rate limit headers from inference (non-Codex providers typically send these)
  if (hasRateData) {
    return (
      <div className="hidden items-center gap-3 md:flex px-2 py-1 rounded-sm border border-border/50 bg-card/50">
        {rateLimitRPM?.limit ? (
          <RateLimitBar label="Req/min" bucket={rateLimitRPM} />
        ) : null}
        {rateLimitRPH?.limit ? (
          <RateLimitBar label="Req/hr" bucket={rateLimitRPH} />
        ) : null}
      </div>
    );
  }

  // Codex is connected but the API doesn't expose usage data proactively —
  // show a minimal "connected" pill so the user knows Codex is active.
  return (
    <div className="hidden items-center gap-1.5 md:flex px-2 py-1 rounded-sm border border-border/50 bg-card/40">
      <Zap className="h-3 w-3 text-primary/70 shrink-0" />
      <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-[0.1em]">Codex</span>
    </div>
  );
}
