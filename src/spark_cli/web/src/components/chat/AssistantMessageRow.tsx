import { memo } from "react";
import { Copy, FileText, Loader2, Zap } from "lucide-react";
import type { TimelineAssistantMessage } from "@/lib/threadTimelineModel";
import { Button } from "@/components/ui/button";
import { Markdown } from "@/components/Markdown";

export interface AssistantMessageRowProps {
  message: TimelineAssistantMessage;
  safeMode?: boolean;
  defaultWrap?: boolean;
  onPromoteToBrief?: (message: TimelineAssistantMessage) => void;
  onCopyExact?: (message: TimelineAssistantMessage) => void;
}

function formatTokens(totalTokens: number): string {
  return totalTokens >= 1000 ? `${(totalTokens / 1000).toFixed(1)}K tokens` : `${totalTokens} tokens`;
}

export const AssistantMessageRow = memo(function AssistantMessageRow({
  message,
  safeMode = false,
  defaultWrap = false,
  onPromoteToBrief,
  onCopyExact,
}: AssistantMessageRowProps) {
  const usage = message.usage;
  const showActions = !message.streaming && Boolean(message.content) && Boolean(onPromoteToBrief || onCopyExact);

  return (
    <article className="group/assistant flex gap-2" data-message-role="assistant" data-message-id={message.id}>
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-primary/15 bg-primary/8 text-primary/75" aria-hidden="true">
        <Zap className="h-3.5 w-3.5" />
      </div>
      <div className="relative min-w-0 w-full max-w-[85%] rounded-lg bg-transparent px-3 py-2 text-sm text-foreground">
        {message.content ? (
          <>
            {Boolean(message.source.liveOmittedChars) && (
              <div className="mb-2 text-[11px] text-muted-foreground/60">
                Showing the latest {message.source.content.length.toLocaleString()} of {message.source.liveTotalChars?.toLocaleString()} characters
                {!message.streaming && "; the complete response remains saved in this session"}
              </div>
            )}
            <Markdown
              content={message.content}
              streaming={message.streaming}
              showStreamingCursor={message.streaming}
              safeMode={safeMode}
              renderRevision={message.source.renderRevision}
              defaultWrap={defaultWrap}
            />
          </>
        ) : (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Loader2 className={`h-3 w-3 ${safeMode ? "" : "animate-spin"}`} />
            <span className="text-xs">Thinking…</span>
          </span>
        )}

        {showActions && (
          <div className="absolute -top-2 right-0 flex gap-1 opacity-0 transition-opacity group-hover/assistant:opacity-100 focus-within:opacity-100">
            {onCopyExact && (
              <Button type="button" variant="ghost" size="icon" className="h-6 w-6" title="Copy complete response" aria-label="Copy complete response" onClick={() => onCopyExact(message)}>
                <Copy className="h-3 w-3" />
              </Button>
            )}
            {onPromoteToBrief && (
              <Button type="button" variant="ghost" size="icon" className="h-6 w-6" title="Promote to brief" aria-label="Promote to brief" onClick={() => onPromoteToBrief(message)}>
                <FileText className="h-3 w-3" />
              </Button>
            )}
          </div>
        )}

        {!message.streaming && usage && usage.totalTokens > 0 && (
          <div className="mt-1 text-[10px] tabular-nums text-muted-foreground/40">
            {formatTokens(usage.totalTokens)}
            {usage.costUsd != null && usage.costUsd > 0 && (
              <> · ${usage.costUsd < 0.01 ? usage.costUsd.toFixed(4) : usage.costUsd.toFixed(2)}</>
            )}
            {usage.model && <span className="ml-1.5">· {usage.model}</span>}
          </div>
        )}
      </div>
    </article>
  );
});
