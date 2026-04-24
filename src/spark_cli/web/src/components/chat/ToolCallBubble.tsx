import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";

export function ToolCallBubble({
  name,
  args,
  result,
  done,
}: {
  name: string;
  args: Record<string, unknown>;
  result?: string;
  done?: boolean;
}) {
  const [open, setOpen] = useState(!done);
  let argsStr: string;
  try {
    argsStr = JSON.stringify(args, null, 2);
  } catch {
    argsStr = String(args);
  }

  return (
    <div
      className={`rounded-md border text-xs ${
        done ? "border-success/30 bg-success/5" : "border-warning/30 bg-warning/5"
      }`}
    >
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 cursor-pointer hover:bg-foreground/5 transition-colors text-left"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <Wrench className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
        <span className="font-mono font-medium text-foreground">{name}</span>
        <span className="ml-auto text-[10px] uppercase tracking-wider text-muted-foreground">
          {done ? "done" : "running"}
        </span>
      </button>
      {open && (
        <div className="border-t border-border/50 px-3 py-2 space-y-2">
          <pre className="text-[11px] overflow-x-auto whitespace-pre-wrap font-mono text-muted-foreground max-h-40 overflow-y-auto">
            {argsStr}
          </pre>
          {result != null && result !== "" && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Result</div>
              <pre className="text-[11px] overflow-x-auto whitespace-pre-wrap font-mono text-foreground/90 max-h-48 overflow-y-auto">
                {result.length > 12000 ? `${result.slice(0, 12000)}…` : result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
