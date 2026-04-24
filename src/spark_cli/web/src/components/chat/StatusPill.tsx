import { Loader2 } from "lucide-react";

export function StatusPill({
  streaming,
  label,
}: {
  streaming: boolean;
  label?: string | null;
}) {
  if (!streaming && !label) return null;
  const text = label || (streaming ? "Thinking…" : "");
  if (!text) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary/40 px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
      {streaming && <Loader2 className="h-3 w-3 animate-spin" />}
      <span className="truncate max-w-[220px]">{text}</span>
    </span>
  );
}
