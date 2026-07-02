import { memo, useMemo } from "react";
import { cn } from "@/lib/utils";

export type TimelineKind =
  | "user"
  | "assistant"
  | "tool"
  | "reasoning"
  | "approval"
  | "note"
  | "feedback"
  | "typing";

export interface TimelineSourceItem {
  id: string;
  index: number;
  role: TimelineKind;
  streaming?: boolean;
  done?: boolean;
  resultTruncated?: boolean;
  hasError?: boolean;
}

export interface TimelineMinimapItem {
  id: string;
  index: number;
  kind: TimelineKind;
  active: boolean;
  error: boolean;
}

export function buildTimelineMinimapItems(items: TimelineSourceItem[]): TimelineMinimapItem[] {
  return items.map((item) => ({
    id: item.id,
    index: item.index,
    kind: item.role,
    active: Boolean(item.streaming || item.role === "typing"),
    error: Boolean(item.hasError || item.resultTruncated || (item.role === "tool" && item.done === false)),
  }));
}

function markerClassName(item: TimelineMinimapItem): string {
  if (item.error) return "bg-destructive";
  if (item.active) return "bg-success";
  switch (item.kind) {
    case "user":
      return "bg-primary";
    case "assistant":
      return "bg-foreground/65";
    case "tool":
      return "bg-amber-500/80";
    case "reasoning":
      return "bg-cyan-500/75";
    case "approval":
      return "bg-fuchsia-500/75";
    case "note":
      return "bg-muted-foreground/60";
    case "feedback":
      return "bg-indigo-500/70";
    case "typing":
      return "bg-success";
  }
}

function markerLabel(item: TimelineMinimapItem): string {
  const role = item.kind === "typing" ? "streaming" : item.kind;
  const suffix = item.error ? ", needs attention" : item.active ? ", active" : "";
  return `${role} row ${item.index + 1}${suffix}`;
}

export const TimelineMinimap = memo(function TimelineMinimap({
  items,
  visibleStartIndex,
  visibleEndIndex,
  onJumpToIndex,
  className,
}: {
  items: TimelineMinimapItem[];
  visibleStartIndex: number;
  visibleEndIndex: number;
  onJumpToIndex: (index: number) => void;
  className?: string;
}) {
  const visible = useMemo(() => {
    if (items.length === 0) return { top: 0, height: 0 };
    const start = Math.max(0, Math.min(visibleStartIndex, items.length - 1));
    const end = Math.max(start, Math.min(visibleEndIndex, items.length - 1));
    const top = (start / items.length) * 100;
    const height = Math.max(7, ((end - start + 1) / items.length) * 100);
    return { top, height: Math.min(100 - top, height) };
  }, [items.length, visibleEndIndex, visibleStartIndex]);

  if (items.length < 8) return null;

  return (
    <div
      className={cn(
        "pointer-events-auto absolute right-1 top-3 bottom-3 z-20 hidden w-4 flex-col items-center rounded-md border border-border/50 bg-background/75 py-1 shadow-sm backdrop-blur md:flex",
        className,
      )}
      aria-label="Chat timeline"
    >
      <div className="relative h-full w-full">
        <div
          className="absolute left-1/2 w-2 -translate-x-1/2 rounded-full border border-primary/45 bg-primary/12"
          style={{ top: `${visible.top}%`, height: `${visible.height}%` }}
          aria-hidden="true"
        />
        {items.map((item) => {
          const top = items.length <= 1 ? 0 : (item.index / (items.length - 1)) * 100;
          return (
            <button
              key={item.id}
              type="button"
              aria-label={markerLabel(item)}
              title={markerLabel(item)}
              onClick={() => onJumpToIndex(item.index)}
              className={cn(
                "absolute left-1/2 h-1.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full opacity-75 transition hover:h-2 hover:w-3 hover:opacity-100 focus:outline-none focus:ring-1 focus:ring-ring",
                markerClassName(item),
              )}
              style={{ top: `${top}%` }}
            />
          );
        })}
      </div>
    </div>
  );
});
