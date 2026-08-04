import { useEffect, useState } from "react";
import { Wrench } from "lucide-react";
import {
  DEFAULT_OPTIMISTIC_TTL_MS,
  resolveChatStatus,
  type ChatConnectionState,
} from "@/lib/chatStatus";

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
  turnActive,
  backendState,
  backendPhase,
  backendStatus,
  sessionActive,
  connection,
  optimisticAt,
  now,
}: {
  streaming: boolean;
  label?: string | null;
  turnActive?: boolean | null;
  backendState?: string | null;
  backendPhase?: string | null;
  backendStatus?: string | null;
  sessionActive?: boolean | null;
  connection?: ChatConnectionState | null;
  optimisticAt?: number | null;
  now?: number;
}) {
  const [clock, setClock] = useState(() => Date.now());
  const hasConfirmedSnapshot = turnActive !== undefined
    || backendState !== undefined
    || backendPhase !== undefined
    || backendStatus !== undefined
    || sessionActive !== undefined
    || connection !== undefined;
  useEffect(() => {
    if (!hasConfirmedSnapshot || optimisticAt == null || now !== undefined) return;
    const expiresIn = Math.max(0, optimisticAt + DEFAULT_OPTIMISTIC_TTL_MS - clock + 1);
    const timer = window.setTimeout(() => setClock(Date.now()), expiresIn);
    return () => window.clearTimeout(timer);
  }, [clock, hasConfirmedSnapshot, now, optimisticAt]);
  const effectiveNow = now ?? clock;
  const resolved = hasConfirmedSnapshot
    ? resolveChatStatus({
        turnActive,
        backendState,
        backendPhase,
        backendLabel: backendStatus,
        sessionActive,
        connection,
        optimisticLabel: label,
        optimisticAt,
        now: effectiveNow,
      })
    : null;
  const effectiveLabel = resolved?.label ?? (resolved?.staleOptimistic ? null : label);
  const effectiveStreaming = resolved ? resolved.kind !== "idle" : streaming;
  if (!effectiveStreaming && !effectiveLabel) return null;

  const isToolLabel = effectiveLabel?.startsWith("Tool");
  const isModelLoading = effectiveStreaming && isModelLoadingLabel(effectiveLabel);

  if (isModelLoading) {
    return (
      <span
        className="spark-status-shimmer relative inline-flex h-6 w-[13.25rem] items-center justify-center gap-2 overflow-hidden rounded-full border border-border bg-secondary/40 px-2.5 text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
        data-state={resolved?.kind ?? "model-loading"}
      >
        <span className="spark-status-breathe h-1.5 w-1.5 rounded-full bg-muted-foreground/70" />
        <span className="relative z-10 whitespace-nowrap">{MODEL_LOADING_LABEL}</span>
      </span>
    );
  }

  const text = effectiveLabel || "";
  return (
    <span className="inline-flex h-6 max-w-[13.25rem] items-center gap-1.5 rounded-full border border-border bg-secondary/40 px-2.5 text-[10px] uppercase tracking-wider text-muted-foreground" data-status-kind={resolved?.kind} data-status-source={resolved?.source}>
      {isToolLabel && <Wrench className="h-3 w-3 shrink-0" />}
      <span className="truncate max-w-[220px]">{text}</span>
    </span>
  );
}
