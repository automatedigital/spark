export type TimelineKind =
  | "user"
  | "assistant"
  | "tool"
  | "reasoning"
  | "approval"
  | "note"
  | "feedback"
  | "typing";

export type TimelineLandmarkKind =
  | "user-turn"
  | "final-answer"
  | "active-work"
  | "failure"
  | "approval";

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

export interface TimelineTurnLandmarkSource {
  id: string;
  turnIndex: number;
  kind: TimelineLandmarkKind;
  label?: string;
  active?: boolean;
  error?: boolean;
}

export interface TimelineMinimapLandmark extends TimelineTurnLandmarkSource {
  active: boolean;
  error: boolean;
}

export const MAX_RENDERED_TIMELINE_LANDMARKS = 160;

function sampleEvenly<T>(items: readonly T[], limit: number): T[] {
  if (limit <= 0) return [];
  if (items.length <= limit) return [...items];
  if (limit === 1) return [items.at(-1)!];
  return Array.from({ length: limit }, (_, index) => (
    items[Math.round(index * (items.length - 1) / (limit - 1))]
  ));
}

/**
 * Bound the interactive DOM used by the minimap. Important states receive up
 * to half the marker budget and the remaining user/answer landmarks are
 * sampled evenly, retaining navigation across the full conversation without
 * mounting thousands of overlapping buttons.
 */
export function limitTimelineLandmarks(
  landmarks: readonly TimelineMinimapLandmark[],
  limit = MAX_RENDERED_TIMELINE_LANDMARKS,
): TimelineMinimapLandmark[] {
  if (landmarks.length <= limit) return [...landmarks];
  const important = landmarks.filter((item) => (
    item.active || item.error || item.kind === "active-work" || item.kind === "failure" || item.kind === "approval"
  ));
  const importantIds = new Set(important.map((item) => item.id));
  const ordinary = landmarks.filter((item) => !importantIds.has(item.id));
  const importantBudget = Math.min(important.length, Math.max(1, Math.floor(limit / 2)));
  const selected = [
    ...sampleEvenly(important, importantBudget),
    ...sampleEvenly(ordinary, Math.max(0, limit - importantBudget)),
  ];
  return selected.sort((left, right) => (
    left.turnIndex - right.turnIndex || left.kind.localeCompare(right.kind)
  ));
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

/**
 * Keep the minimap useful on long threads by representing turns, not every
 * repetitive tool row. One turn can contribute multiple meaningful landmarks:
 * its prompt, final answer, and any active/failing/approval state.
 */
export function buildTurnLandmarks(turns: readonly {
  id: string;
  userMessage?: unknown;
  finalAnswer?: unknown;
  status: string;
  workItems: readonly { kind: string; failed?: boolean; resolved?: boolean; requestedInput?: { resolved?: boolean } }[];
}[]): TimelineMinimapLandmark[] {
  const landmarks: TimelineMinimapLandmark[] = [];
  turns.forEach((turn, turnIndex) => {
    if (turn.userMessage) {
      landmarks.push({
        id: `${turn.id}:user`,
        turnIndex,
        kind: "user-turn",
        label: `Turn ${turnIndex + 1} · user message`,
        active: false,
        error: false,
      });
    }
    if (turn.finalAnswer) {
      landmarks.push({
        id: `${turn.id}:answer`,
        turnIndex,
        kind: "final-answer",
        label: `Turn ${turnIndex + 1} · final answer`,
        active: false,
        error: false,
      });
    }
    const hasFailure = turn.status === "failed" || turn.workItems.some((item) => item.kind === "tool" && item.failed);
    const hasApproval = turn.status === "awaiting-approval" || turn.workItems.some((item) => item.kind === "approval" && !item.resolved);
    const hasUnresolvedInput = turn.status === "awaiting-input" || turn.workItems.some((item) => item.kind === "requested-input" && !item.requestedInput?.resolved);
    if (hasFailure) {
      landmarks.push({ id: `${turn.id}:failure`, turnIndex, kind: "failure", label: `Turn ${turnIndex + 1} · needs attention`, active: false, error: true });
    } else if (hasApproval || hasUnresolvedInput) {
      landmarks.push({ id: `${turn.id}:approval`, turnIndex, kind: "approval", label: `Turn ${turnIndex + 1} · input needed`, active: true, error: true });
    } else if (turn.status === "active") {
      landmarks.push({ id: `${turn.id}:active`, turnIndex, kind: "active-work", label: `Turn ${turnIndex + 1} · active work`, active: true, error: false });
    }
  });
  return landmarks;
}
