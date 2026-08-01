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
