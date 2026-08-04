import { memo, useMemo } from "react";
import { cn } from "@/lib/utils";
import type { TimelineMinimapItem, TimelineMinimapLandmark } from "./timelineMinimapModel";
import { limitTimelineLandmarks } from "./timelineMinimapModel";

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

function landmarkClassName(item: TimelineMinimapLandmark): string {
  if (item.error) return "bg-destructive";
  if (item.active) return "bg-success";
  switch (item.kind) {
    case "user-turn": return "bg-primary";
    case "final-answer": return "bg-foreground/65";
    case "active-work": return "bg-success";
    case "failure": return "bg-destructive";
    case "approval": return "bg-fuchsia-500/75";
  }
}

function landmarkLabel(item: TimelineMinimapLandmark): string {
  return item.label ?? `Turn ${item.turnIndex + 1} · ${item.kind}`;
}

export const TimelineMinimap = memo(function TimelineMinimap({
  items = [],
  visibleStartIndex = 0,
  visibleEndIndex = 0,
  onJumpToIndex,
  landmarks,
  visibleStartTurnIndex = 0,
  visibleEndTurnIndex = 0,
  onJumpToTurn,
  className,
}: {
  items?: TimelineMinimapItem[];
  visibleStartIndex?: number;
  visibleEndIndex?: number;
  onJumpToIndex?: (index: number) => void;
  landmarks?: TimelineMinimapLandmark[];
  visibleStartTurnIndex?: number;
  visibleEndTurnIndex?: number;
  onJumpToTurn?: (turnIndex: number) => void;
  className?: string;
}) {
  const usingLandmarks = Boolean(landmarks);
  const landmarkItems = useMemo(() => limitTimelineLandmarks(landmarks ?? []), [landmarks]);
  const markerCount = usingLandmarks ? landmarkItems.length : items.length;
  const maxTurnIndex = landmarkItems.reduce((max, item) => Math.max(max, item.turnIndex), 0);
  const visible = useMemo(() => {
    if (markerCount === 0) return { top: 0, height: 0 };
    const range = usingLandmarks ? Math.max(maxTurnIndex, 1) : markerCount;
    const start = usingLandmarks
      ? Math.max(0, Math.min(visibleStartTurnIndex, range))
      : Math.max(0, Math.min(visibleStartIndex, markerCount - 1));
    const end = usingLandmarks
      ? Math.max(start, Math.min(visibleEndTurnIndex, range))
      : Math.max(start, Math.min(visibleEndIndex, markerCount - 1));
    const top = (start / range) * 100;
    const height = Math.max(7, ((end - start + 1) / range) * 100);
    return { top, height: Math.min(100 - top, height) };
  }, [markerCount, maxTurnIndex, usingLandmarks, visibleEndIndex, visibleEndTurnIndex, visibleStartIndex, visibleStartTurnIndex]);

  if (markerCount < (usingLandmarks ? 4 : 8)) return null;

  const markerButtons = usingLandmarks
    ? landmarkItems.map((item) => ({
      id: item.id,
      label: landmarkLabel(item),
      top: maxTurnIndex <= 0 ? 0 : (item.turnIndex / maxTurnIndex) * 100,
      left: item.kind === "user-turn" ? "25%" : item.kind === "final-answer" ? "75%" : "50%",
      className: landmarkClassName(item),
      onJump: () => onJumpToTurn?.(item.turnIndex),
    }))
    : items.map((item) => ({
      id: item.id,
      label: markerLabel(item),
      top: markerCount <= 1 ? 0 : (item.index / (markerCount - 1)) * 100,
      left: "50%",
      className: markerClassName(item),
      onJump: () => onJumpToIndex?.(item.index),
    }));

  const moveMarkerFocus = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowRight" && event.key !== "ArrowUp" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const buttons = Array.from(event.currentTarget.closest("[data-timeline-minimap]")?.querySelectorAll<HTMLButtonElement>("[data-timeline-marker]") ?? []);
    const index = buttons.indexOf(event.currentTarget);
    const direction = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : -1;
    buttons[(index + direction + buttons.length) % buttons.length]?.focus();
  };

  return (
    <div
      className={cn(
        "pointer-events-auto absolute right-1 top-3 bottom-3 z-20 hidden w-6 flex-col items-center rounded-md border border-border/50 bg-background/75 py-1 shadow-sm backdrop-blur md:flex",
        className,
      )}
      aria-label={usingLandmarks ? "Conversation turn landmarks" : "Chat timeline"}
      role="navigation"
      data-timeline-minimap
    >
      <div className="relative h-full w-full">
        <div
          className="absolute left-1/2 w-2 -translate-x-1/2 rounded-full border border-primary/45 bg-primary/12"
          style={{ top: `${visible.top}%`, height: `${visible.height}%` }}
          aria-hidden="true"
        />
        {markerButtons.map((item) => {
          return (
            <button
              key={item.id}
              type="button"
              aria-label={item.label}
              title={item.label}
              data-timeline-marker
              onKeyDown={moveMarkerFocus}
              onClick={item.onJump}
              className={cn(
                "absolute h-3 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-background opacity-80 transition hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 focus:ring-offset-background",
                item.className,
              )}
              style={{ top: `${item.top}%`, left: item.left }}
            />
          );
        })}
      </div>
    </div>
  );
});
