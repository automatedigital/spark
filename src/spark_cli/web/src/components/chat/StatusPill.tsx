import { useEffect, useState } from "react";
import { Wrench } from "lucide-react";

const THINKING_PHRASES = ["Thinking…", "Reasoning…", "Working…", "Processing…"];

export function StatusPill({
  streaming,
  label,
}: {
  streaming: boolean;
  label?: string | null;
}) {
  const [phraseIdx, setPhraseIdx] = useState(0);

  // Cycle through thinking phrases every 2 seconds when idle-streaming
  const isIdleThinking = streaming && !label;
  useEffect(() => {
    if (!isIdleThinking) return;
    const t = setInterval(() => setPhraseIdx((i) => (i + 1) % THINKING_PHRASES.length), 2000);
    return () => clearInterval(t);
  }, [isIdleThinking]);

  if (!streaming && !label) return null;

  const isToolLabel = label?.startsWith("Tool:");

  if (isIdleThinking) {
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-2.5 py-0.5 text-[10px] uppercase tracking-wider text-primary/70">
        <span className="flex gap-[3px] items-center">
          <span className="h-1.5 w-1.5 rounded-full bg-primary/60 animate-bounce [animation-delay:0ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-primary/60 animate-bounce [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 rounded-full bg-primary/60 animate-bounce [animation-delay:300ms]" />
        </span>
        <span>{THINKING_PHRASES[phraseIdx]}</span>
      </span>
    );
  }

  const text = label || "";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary/40 px-2 py-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
      {isToolLabel && <Wrench className="h-3 w-3 shrink-0" />}
      <span className="truncate max-w-[220px]">{text}</span>
    </span>
  );
}
