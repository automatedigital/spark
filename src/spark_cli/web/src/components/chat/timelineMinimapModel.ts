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
