import { Wrench } from "lucide-react";

export const MODEL_LOADING_LABEL = "Loading LLM response";

const MODEL_LOADING_ALIASES = new Set([
  MODEL_LOADING_LABEL,
  "Thinking…",
  "Reasoning…",
  "Working…",
  "Processing…",
  "Still working…",
  "Waiting for provider response…",
  "Calling model…",
]);

function isModelLoadingLabel(label: string | null | undefined): boolean {
  if (!label) return true;
  return (
    MODEL_LOADING_ALIASES.has(label) ||
    label.startsWith("Waiting for provider response") ||
    label.startsWith("Calling model")
  );
}

export function StatusPill({
  streaming,
  label,
}: {
  streaming: boolean;
  label?: string | null;
}) {
  if (!streaming && !label) return null;

  const isToolLabel = label?.startsWith("Tool:");
  const isModelLoading = streaming && isModelLoadingLabel(label);

  if (isModelLoading) {
    return (
      <span
        className="spark-status-shimmer relative inline-flex h-6 w-[13.25rem] items-center justify-center gap-2 overflow-hidden rounded-full border border-border bg-secondary/40 px-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
        data-state="model-loading"
      >
        <span className="spark-status-breathe h-1.5 w-1.5 rounded-full bg-muted-foreground/70" />
        <span className="relative z-10 whitespace-nowrap">{MODEL_LOADING_LABEL}</span>
      </span>
    );
  }

  const text = label || "";
  return (
    <span className="inline-flex h-6 max-w-[13.25rem] items-center gap-1.5 rounded-full border border-border bg-secondary/40 px-2.5 text-[10px] uppercase tracking-wider text-muted-foreground">
      {isToolLabel && <Wrench className="h-3 w-3 shrink-0" />}
      <span className="truncate max-w-[220px]">{text}</span>
    </span>
  );
}
