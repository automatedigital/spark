import { useState } from "react";
import { Brain, ChevronDown, ChevronRight } from "lucide-react";

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

export function ReasoningBubble({ text, isActive }: { text: string; isActive?: boolean }) {
  const [open, setOpen] = useState(false);
  const words = wordCount(text);
  const preview = text.length > 100 ? text.slice(0, 100).trimEnd() + "…" : null;

  return (
    <div className="rounded-md bg-foreground/[0.035] text-xs overflow-hidden">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 cursor-pointer hover:bg-foreground/5 transition-colors"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <Brain className={`h-3.5 w-3.5 shrink-0 ${open || isActive ? "text-primary/60 animate-pulse" : "text-muted-foreground"}`} />
        <span className="text-muted-foreground">Reasoning</span>
        <span className="ml-auto flex items-center gap-1.5 text-[10px] text-muted-foreground/50 shrink-0">
          {isActive && <span className="h-1.5 w-1.5 rounded-full bg-[var(--spark-accent)] animate-pulse" />}
          ~{words} words
        </span>
      </button>

      {!open && preview && (
        <div className="px-3 pb-2 text-muted-foreground/60 italic text-[11px] leading-relaxed relative">
          {preview}
          <div className="absolute bottom-0 left-0 right-0 h-4 bg-gradient-to-t from-muted/20 to-transparent pointer-events-none" />
        </div>
      )}

      <div
        className={`overflow-hidden transition-all duration-200 ease-in-out ${open ? "max-h-[400px]" : "max-h-0"}`}
      >
        <div className="border-t border-border/45 px-3 py-2 text-muted-foreground leading-relaxed whitespace-pre-wrap overflow-y-auto max-h-[400px]">
          {text}
        </div>
      </div>
    </div>
  );
}
