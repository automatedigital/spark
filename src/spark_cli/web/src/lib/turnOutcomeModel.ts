import type { WebTurnOutcome } from "./api";
import type { TimelineTurn } from "./threadTimelineModel";

/** Match durable outcomes to persisted turns, including turns with no answer. */
export function outcomeForTimelineTurn(
  turn: TimelineTurn,
  outcomes: readonly WebTurnOutcome[],
  isLatestTurn: boolean,
): WebTurnOutcome | null {
  const matched = outcomes.find((outcome) => (
    (outcome.assistant_message_id != null && turn.finalAnswer?.id === `db:${outcome.assistant_message_id}`)
    || (outcome.user_message_id != null && turn.userMessage?.id === `db:${outcome.user_message_id}`)
  ));
  return matched ?? (isLatestTurn ? outcomes.at(-1) ?? null : null);
}
