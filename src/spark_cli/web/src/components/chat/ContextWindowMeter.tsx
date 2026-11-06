import { useCallback, useEffect, useId, useRef, useState } from "react";
import { contextCompactionApi, type ContextPreflight, type ContextCompactionResult } from "@/lib/api_context_compaction";
import { Loader2, Pin, X } from "lucide-react";
import { contextApi, type ContextEstimate, type ContextItem, type InclusionMode } from "@/lib/context";
import { contextModeSummary, contextPressureLevel, formatContextTokens } from "./contextWindowPolicy";

export interface ContextWindowMeterProps {
  sessionId?: string | null;
  promptText?: string;
  streaming?: boolean;
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
  estimate: suppliedEstimate,
  sessionId,
  promptText = "",
  streaming = false,
  loading,
  contextItems = [],
  onRemoveItem,
  onUpdateMode,
}: ContextWindowMeterProps) {
  const [compactedEstimate, setCompactedEstimate] = useState<ContextEstimate | null>(null);
  const estimate = compactedEstimate ?? suppliedEstimate;
  const [preflight, setPreflight] = useState<ContextPreflight | null>(null);
  const [result, setResult] = useState<ContextCompactionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [compacting, setCompacting] = useState(false);
  const owner = useRef(sessionId);
  owner.current = sessionId;
  const [expanded, setExpanded] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogId = useId().replace(/:/g, "");

  const closeDialog = useCallback(() => {
    setExpanded(false);
    triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!expanded) return;

    closeRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      closeDialog();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [closeDialog, expanded]);

  useEffect(() => { setCompactedEstimate(null); }, [suppliedEstimate, sessionId, streaming]);

  useEffect(() => {
    setPreflight(null);
    setResult(null);
    setError(null);
    setCompacting(false);
    if (!expanded || !sessionId) return;
    const controller = new AbortController();
    let active = true;
    contextCompactionApi.preflight(sessionId, controller.signal).then((value) => {
      if (active) setPreflight(value);
    }).catch((cause) => {
      if (active) setError(cause instanceof Error ? cause.message : "Preflight unavailable");
    });
    return () => { active = false; controller.abort(); };
  }, [expanded, sessionId, streaming]);

  const compact = async () => {
    if (!sessionId || !preflight || streaming || compacting) return;
    const initiatingSession = sessionId;
    setCompacting(true);
    setError(null);
    try {
      const value = await contextCompactionApi.compact(sessionId, preflight.revision);
      if (owner.current !== initiatingSession) return;
      setResult(value);
      setPreflight(null);
      if (value.status === "compacted") {
        contextApi.estimateTokens({ sessionId: initiatingSession, promptText, contextItems }).then((fresh) => {
          if (owner.current === initiatingSession) setCompactedEstimate(fresh);
        }).catch(() => { /* The committed result remains valid if refresh fails. */ });
      }
    } catch (cause) {
      if (owner.current === initiatingSession) {
        setError(cause instanceof Error ? cause.message : "Compaction failed; saved context is intact.");
        setPreflight(null);
      }
    } finally {
      if (owner.current === initiatingSession) setCompacting(false);
    }
  };

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
        ref={triggerRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={expanded}
        aria-controls={`context-window-${dialogId}`}
        onClick={() => {
          if (expanded) closeDialog();
          else setExpanded(true);
        }}
        title="Estimated context window usage"
        className={`rounded px-1.5 py-1 text-[10px] tabular-nums transition hover:bg-foreground/6 ${colorClass}`}
      >
        Est. {formatContextTokens(estimate.total_tokens)} / {formatContextTokens(estimate.context_window)}
      </button>
      {expanded && (
        <div
          id={`context-window-${dialogId}`}
          role="dialog"
          aria-label="Estimated context window"
          className="absolute bottom-full right-0 z-50 mb-2 max-h-[min(80vh,38rem)] w-72 overflow-y-auto rounded-xl border border-border bg-popover/95 p-3 text-[11px] shadow-xl backdrop-blur-xl"
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <div>
              <div className="font-medium text-foreground">Estimated context</div>
              <div className="text-[10px] text-muted-foreground">Provider-reported usage appears after the turn.</div>
            </div>
            <div className="flex items-center gap-2">
              <span className={`tabular-nums ${colorClass}`}>{Math.round(estimate.utilization * 100)}%</span>
              <button
                ref={closeRef}
                type="button"
                aria-label="Close context window details"
                onClick={closeDialog}
                className="rounded p-0.5 text-muted-foreground/60 transition hover:bg-foreground/8 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/60"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          <div className="space-y-1">
            {(estimate.breakdown ?? estimate.buckets).map((bucket) => (
              <div key={bucket.label} className="flex justify-between text-muted-foreground">
                <span title={"basis" in bucket ? bucket.basis : "estimate"}>{bucket.label}</span>
                <span className="tabular-nums" title={"basis" in bucket ? bucket.basis : "estimate"}>{bucket.tokens === null ? "Unknown" : `Est. ${formatContextTokens(bucket.tokens)}`}</span>
              </div>
            ))}
          </div>

          <div className="mt-2 text-[10px] text-muted-foreground">Memory is included in loaded instructions; its separate count and provider actual usage are unknown. Unloaded file content and cold tool schemas are excluded.</div>
          {sessionId && (
            <div className="mt-2 space-y-2 border-t border-border pt-2">
              <div className="font-medium">Compaction preflight</div>
              {preflight && <>
                <p className="text-muted-foreground">{preflight.policy}</p>
                <p className="text-muted-foreground">Protect {preflight.head_messages} first and {preflight.tail_messages} recent messages. Up to {preflight.summary_messages} older prose messages eligible. Summary limit: {preflight.summary_timeout_seconds}s / 32K estimated input / {preflight.summary_output_tokens} output tokens; price unknown.</p>
              </>}
              {streaming && !preflight?.blocked_reason && <p>Wait for the active turn before compacting.</p>}
              {preflight?.blocked_reason && <p>{preflight.blocked_reason}</p>}
              <button type="button" onClick={() => void compact()} disabled={streaming || compacting || !preflight?.can_compact}
                className="rounded bg-secondary px-2 py-1 text-foreground disabled:opacity-40">
                {compacting ? "Compacting…" : "Compact context"}
              </button>
              {result && <p role="status">{result.status === "compacted"
                ? `History estimate ${formatContextTokens(result.before_estimated_tokens)} → ${formatContextTokens(result.after_estimated_tokens)} tokens. Provider actual: unknown. ${result.elapsed_seconds?.toFixed(2) ?? "?"}s. Original transcript retained.`
                : result.reason ?? "No safe reduction available."}</p>}
              {error && <p role="alert" className="text-destructive">{error}</p>}
            </div>
          )}

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
