import { AlertTriangle, CheckCircle2, CircleHelp, Loader2, RefreshCw, Search, WifiOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { type RecoveryCardState } from "@/lib/chatRecovery";

interface RecoveryCardProps {
  state: RecoveryCardState;
  label?: string | null;
  lastEventAt?: number | null;
  busyAction?: "reconnect" | "inspect" | "retry" | null;
  onReconnect: () => void;
  onInspect: () => void;
  onRetry: () => void;
  canRetry?: boolean;
}

function activityLabel(value: number | null | undefined): string {
  if (!value) return "No confirmed activity time";
  return `Last confirmed activity ${new Date(value < 10_000_000_000 ? value * 1000 : value).toLocaleTimeString()}`;
}

export function RecoveryCard({ state, label, lastEventAt, busyAction, onReconnect, onInspect, onRetry, canRetry = true }: RecoveryCardProps) {
  const waiting = state === "waiting-approval" || state === "waiting-input";
  const terminal = state === "failed" || state === "interrupted";
  const title = waiting ? (state === "waiting-approval" ? "Approval needed" : "Input needed")
    : state === "reconnecting" ? "Checking response status" : terminal ? (state === "failed" ? "Response failed" : "Response interrupted") : "Response status";
  const Icon = state === "reconnecting" ? WifiOff : terminal ? AlertTriangle : waiting ? CircleHelp : state === "complete" ? CheckCircle2 : Loader2;
  return (
    <div data-testid="recovery-card" data-recovery-state={state} className="mx-3 my-2 rounded-md border border-border bg-card/60 px-3 py-2 text-xs">
      <div className="flex items-start gap-2">
        <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${terminal ? "text-destructive" : "text-amber-300"} ${state === "running" ? "animate-spin" : ""}`} />
        <div className="min-w-0 flex-1">
          <div className="font-medium text-foreground">{title}</div>
          <div className="mt-0.5 text-muted-foreground">{label ?? (terminal ? "The response did not finish. Review the saved work before retrying." : waiting ? "Resolve the pending decision below to continue." : "Spark has not confirmed a newer event.")}</div>
          <div className="mt-1 text-[10px] text-muted-foreground/80">{activityLabel(lastEventAt)}</div>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {!waiting && state !== "complete" && <Button size="sm" variant="outline" className="h-7 text-[11px]" disabled={busyAction != null} onClick={onReconnect}><RefreshCw className="mr-1 h-3 w-3" />Reconnect</Button>}
        <Button size="sm" variant="ghost" className="h-7 text-[11px]" disabled={busyAction != null} onClick={onInspect}><Search className="mr-1 h-3 w-3" />{terminal ? "Inspect failure" : "Diagnostics"}</Button>
        {terminal && canRetry && <Button size="sm" variant="outline" className="h-7 text-[11px]" disabled={busyAction != null} onClick={onRetry}>Retry response</Button>}
      </div>
    </div>
  );
}
