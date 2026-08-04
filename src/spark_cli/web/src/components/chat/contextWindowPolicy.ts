import type { ContextItem } from "@/lib/context";

export function formatContextTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return String(value);
}

export function contextPressureLevel(utilization: number): "normal" | "warning" | "critical" {
  if (utilization >= 0.95) return "critical";
  if (utilization >= 0.8) return "warning";
  return "normal";
}

export function contextModeSummary(items: readonly ContextItem[]): string[] {
  const summarized = items.filter((item) => item.inclusion_mode === "summary").length;
  const reduced = items.filter((item) => ["path_only", "excerpt", "search", "diff"].includes(item.inclusion_mode)).length;
  return [
    ...(summarized ? [`${summarized} summarized`] : []),
    ...(reduced ? [`${reduced} reduced`] : []),
  ];
}
