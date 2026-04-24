import { useState } from "react";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";

export function ReasoningBubble({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-border/60 bg-muted/20 text-xs">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 cursor-pointer hover:bg-foreground/5 transition-colors"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <Brain className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-muted-foreground italic">Reasoning</span>
      </button>
      {open && (
        <div className="border-t border-border/50 px-3 py-2 text-muted-foreground italic leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto">
          {text}
        </div>
      )}
    </div>
  );
}
