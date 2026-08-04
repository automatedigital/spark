import { memo, useState, type MouseEvent, type ReactNode } from "react";
import { Copy, GitFork, Pencil, RotateCcw, User } from "lucide-react";
import type { ContextItem } from "@/lib/context";
import type { TimelineUserMessage } from "@/lib/threadTimelineModel";
import { Button } from "@/components/ui/button";
import { openExternal } from "@/lib/api";
import { tokenizeUserBubbleText } from "@/lib/userBubbleTokens";
import { isTauri } from "@/sidecar";

const MODE_SHORT: Record<string, string> = {
  path_only: "path",
  excerpt: "excerpt",
  summary: "summary",
  full: "full",
  search: "search",
};

function openMessageLink(event: MouseEvent<HTMLAnchorElement>, href: string) {
  event.stopPropagation();
  if (!isTauri()) return;
  event.preventDefault();
  void openExternal(href);
}

function renderMessageTokens(text: string): ReactNode[] {
  return tokenizeUserBubbleText(text).map((token, index) => {
    if (token.type === "highlight") {
      return <span key={index} className="font-medium text-primary">{token.text}</span>;
    }
    if (token.type === "link") {
      return (
        <a
          key={index}
          href={token.href}
          target="_blank"
          rel="noreferrer"
          onClick={(event) => openMessageLink(event, token.href)}
          className="break-words text-primary/90 underline decoration-primary/25 underline-offset-2 transition-colors hover:text-primary hover:decoration-primary/60"
        >
          {token.text}
        </a>
      );
    }
    return token.text;
  });
}

export interface UserMessageRowProps {
  message: TimelineUserMessage;
  hasSession?: boolean;
  streaming?: boolean;
  onEdit?: (sessionIdx: number, text: string) => void;
  onRetry?: (sessionIdx: number) => void;
  onFork?: (sessionIdx: number) => void;
  onCopy?: (text: string) => void;
}

function ContextChip({ item }: { item: ContextItem }) {
  const [expanded, setExpanded] = useState(false);
  const name = item.label ?? item.source_path?.split("/").pop() ?? item.id;
  const modeLabel = MODE_SHORT[item.inclusion_mode] ?? item.inclusion_mode;

  return (
    <div className="relative">
      <button
        type="button"
        aria-expanded={expanded}
        title={`${name} · ${modeLabel} mode`}
        onClick={() => setExpanded((value) => !value)}
        className="flex items-center gap-1 rounded-md bg-foreground/6 px-1.5 py-0.5 text-[10px] text-muted-foreground transition hover:bg-foreground/9 hover:text-foreground"
      >
        <span className="max-w-[9rem] truncate font-mono">{name}</span>
        <span className="opacity-50">·</span>
        <span>{modeLabel}</span>
      </button>
      {expanded && item.content && (
        <div className="absolute bottom-full right-0 z-50 mb-1 max-h-40 w-72 overflow-y-auto whitespace-pre-wrap rounded-md border border-border bg-popover/95 p-2 text-[11px] font-mono text-foreground/80 shadow-lg backdrop-blur-xl">
          {item.content}
        </div>
      )}
    </div>
  );
}

export const UserMessageRow = memo(function UserMessageRow({
  message,
  hasSession = false,
  streaming = false,
  onEdit,
  onRetry,
  onFork,
  onCopy,
}: UserMessageRowProps) {
  const sessionIdx = message.sessionIdx;
  const canAct = hasSession && sessionIdx != null;

  return (
    <article className="group/user flex flex-row-reverse gap-2" data-message-role="user" data-message-id={message.id}>
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-foreground/8 text-muted-foreground" aria-hidden="true">
        <User className="h-3.5 w-3.5" />
      </div>
      <div className="flex max-w-[85%] flex-col items-end gap-1">
        {message.redirect && <span className="text-[10px] text-muted-foreground/60">↩ redirect</span>}
        <div className="relative rounded-lg bg-foreground/8 px-3 py-2 text-sm text-foreground">
          <p className="whitespace-pre-wrap leading-relaxed">{renderMessageTokens(message.content)}</p>
          {canAct && (
            <div className="absolute -top-2 right-0 flex gap-1 opacity-0 transition-opacity group-hover/user:opacity-100 focus-within:opacity-100">
              {onEdit && (
                <Button type="button" variant="ghost" size="icon" className="h-6 w-6" title="Edit & retry" aria-label="Edit & retry" onClick={() => onEdit(sessionIdx, message.content)}>
                  <Pencil className="h-3 w-3" />
                </Button>
              )}
              {onRetry && (
                <Button type="button" variant="ghost" size="icon" className="h-6 w-6" title="Retry" aria-label="Retry" disabled={streaming} onClick={() => onRetry(sessionIdx)}>
                  <RotateCcw className="h-3 w-3" />
                </Button>
              )}
              {onFork && (
                <Button type="button" variant="ghost" size="icon" className="h-6 w-6" title="Fork from here" aria-label="Fork from here" disabled={streaming} onClick={() => onFork(sessionIdx)}>
                  <GitFork className="h-3 w-3" />
                </Button>
              )}
              {onCopy && (
                <Button type="button" variant="ghost" size="icon" className="h-6 w-6" title="Copy" aria-label="Copy" onClick={() => onCopy(message.content)}>
                  <Copy className="h-3 w-3" />
                </Button>
              )}
            </div>
          )}
        </div>
        {message.source.contextItems && message.source.contextItems.length > 0 && (
          <div className="flex flex-wrap justify-end gap-1">
            {message.source.contextItems.map((item) => <ContextChip key={item.id} item={item} />)}
          </div>
        )}
      </div>
    </article>
  );
});
