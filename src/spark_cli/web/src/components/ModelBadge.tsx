import { useEffect, useState } from "react";
import { Brain, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { shortModelName } from "@/components/chat/PromptBar";

export function ModelBadge() {
  const [smartModel, setSmartModel] = useState<string | null>(null);
  const [effort, setEffort] = useState<string>("none");
  const [reasoningSupported, setReasoningSupported] = useState(false);
  const [multiModel, setMultiModel] = useState(false);

  useEffect(() => {
    api.getModelStatus().then((s) => {
      setSmartModel(s.smart_model || null);
      setEffort(s.reasoning_effort || "none");
      setReasoningSupported(s.reasoning_supported);
      setMultiModel(s.multi_model_enabled);
    }).catch(() => {});
  }, []);

  if (!smartModel) return null;

  const EFFORT_LABELS: Record<string, string> = {
    low: "Low", medium: "Medium", high: "High", xhigh: "Max", minimal: "Minimal",
  };
  const effortLabel = EFFORT_LABELS[effort] ?? "";

  return (
    <div className="hidden items-center gap-1.5 md:flex text-[11px] text-muted-foreground/50 font-medium select-none">
      <span>{shortModelName(smartModel)}</span>
      {reasoningSupported && effortLabel && (
        <>
          <span className="text-muted-foreground/25">·</span>
          <span className="flex items-center gap-0.5 text-primary/60">
            <Brain className="h-3 w-3" />
            {effortLabel}
          </span>
        </>
      )}
      {multiModel && (
        <span title="Multi-model routing active">
          <Zap className="h-3 w-3 text-amber-400/60" />
        </span>
      )}
    </div>
  );
}
