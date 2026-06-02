/* eslint-disable react-refresh/only-export-components */
import { MessageSquare, Trash2 } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { TypeOnTitle } from "@/components/chat/TypeOnTitle";
import type { SessionInfo } from "@/lib/api";

export function threadTitle(session: SessionInfo | null | undefined) {
  if (!session) return "New thread";
  const title = session.title?.trim();
  if (title && title !== "Untitled") return title;
  return session.preview?.trim() || "Untitled thread";
}

export function modelShort(model: string | null | undefined) {
  return (model ?? "").split("/").pop() || "";
}

export function sourceLabel(source: string | null | undefined) {
  const s = (source ?? "").toLowerCase();
  if (s === "cli") return "TUI";
  if (s === "web") return "Web";
  if (!s) return "Unknown";
  return s.replace(/(^|[_-])(\w)/g, (_, sep: string, chr: string) => `${sep ? " " : ""}${chr.toUpperCase()}`);
}

export function ThreadRow({
  session,
  active,
  searchSnippet,
  onOpen,
  onDelete,
}: {
  session: SessionInfo;
  active: boolean;
  searchSnippet?: string;
  onOpen: () => void;
  onDelete: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      className={cn(
        "spark-list-row group relative flex w-full min-w-0 items-start gap-2 border-b border-border px-2.5 py-2 text-left transition",
        active ? "bg-primary/12" : "hover:bg-secondary/45",
      )}
    >
      <span
        className={cn(
          "mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-sm border",
          session.is_active
            ? "border-primary/45 bg-primary/18 text-primary"
            : "border-border bg-secondary/60 text-muted-foreground",
        )}
      >
        <MessageSquare className="h-3.5 w-3.5" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <TypeOnTitle text={threadTitle(session)} className="truncate text-[13px] font-medium text-foreground" />
          {session.is_active && (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary shadow-[0_0_12px_rgba(255,163,43,0.8)]" />
          )}
        </span>
        <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
          {searchSnippet || session.preview || "No messages yet"}
        </span>
        <span className="mt-1 flex min-w-0 items-center gap-1.5 text-[10px] leading-4 text-muted-foreground">
          {modelShort(session.model) && (
            <>
              <span className="truncate font-mono-ui max-w-[96px]">{modelShort(session.model)}</span>
              <span className="text-border">·</span>
            </>
          )}
          <span>{sourceLabel(session.source)}</span>
          <span className="text-border">·</span>
          <span>{session.message_count} msgs</span>
          <span className="text-border">·</span>
          <span>{timeAgo(session.last_active)}</span>
        </span>
      </span>
      <span
        className="absolute right-1.5 top-1.5 opacity-0 transition group-hover:opacity-100"
        onClick={(e) => e.stopPropagation()}
      >
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6 text-muted-foreground hover:text-destructive"
          title="Delete thread"
          onClick={onDelete}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </span>
    </div>
  );
}
