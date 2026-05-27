import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, FileText } from "lucide-react";
import { briefApi } from "@/lib/context";

interface BriefPanelProps {
  sessionId: string;
}

export function BriefPanel({ sessionId }: BriefPanelProps) {
  const [text, setText] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [saving, setSaving] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestTextRef = useRef(text);

  // Load brief on mount / session change
  useEffect(() => {
    briefApi.get(sessionId).then((r) => {
      setText(r.text);
      latestTextRef.current = r.text;
    }).catch(() => {});
  }, [sessionId]);

  function handleChange(value: string) {
    setText(value);
    latestTextRef.current = value;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setSaving(true);
      briefApi.set(sessionId, latestTextRef.current).finally(() => setSaving(false));
    }, 1200);
  }

  const isEmpty = !text.trim();

  return (
    <div className="border-b border-border/50 bg-muted/20">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-1.5 px-3 py-1.5 text-[11px] text-muted-foreground/60 hover:text-muted-foreground transition select-none"
      >
        <FileText className="h-3 w-3 shrink-0" />
        <span className="font-medium">Session brief</span>
        {!isEmpty && !expanded && (
          <span className="ml-1 truncate max-w-[200px] text-muted-foreground/40 italic">{text.split("\n")[0]}</span>
        )}
        {saving && <span className="ml-auto text-muted-foreground/30">saving…</span>}
        <span className="ml-auto shrink-0">
          {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </span>
      </button>
      {expanded && (
        <div className="px-3 pb-2">
          <textarea
            value={text}
            onChange={(e) => handleChange(e.target.value)}
            placeholder="Add a brief — key decisions, constraints, or background the model should always know…"
            rows={4}
            className="w-full resize-none rounded-md border border-border/50 bg-background px-2 py-1.5 text-[12px] text-foreground placeholder:text-muted-foreground/30 focus:outline-none focus:ring-1 focus:ring-primary/40"
          />
        </div>
      )}
    </div>
  );
}
