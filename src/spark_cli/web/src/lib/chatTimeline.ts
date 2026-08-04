import type { ChatMessage } from "./chatTranscriptMerge";
import {
  buildTimelineMinimapItems,
  type TimelineMinimapItem,
  type TimelineSourceItem,
} from "../components/chat/timelineMinimapModel";

export type CollapsedMessageItem = {
  msg: ChatMessage;
  repeatCount: number;
  id: string;
};

export type SyntheticTypingItem = {
  msg: null;
  id: "typing";
};

export type CollapsedItem = CollapsedMessageItem | SyntheticTypingItem;

type ToolMessage = Extract<ChatMessage, { role: "tool" }>;

function toolDurationSeconds(msg: ToolMessage): number | undefined {
  if (typeof msg.durationSeconds === "number") return Math.max(0, msg.durationSeconds);
  if (typeof msg.startedAt === "number" && typeof msg.endedAt === "number") {
    return Math.max(0, msg.endedAt - msg.startedAt);
  }
  return undefined;
}

/** Collapse adjacent tool rows with the same name, preserving the current row behavior. */
export function collapseConsecutiveToolCalls(messages: ChatMessage[]): CollapsedMessageItem[] {
  const collapsed: CollapsedMessageItem[] = [];

  for (const msg of messages) {
    const previous = collapsed[collapsed.length - 1];
    if (
      msg.role === "tool" &&
      previous?.msg.role === "tool" &&
      msg.name === previous.msg.name
    ) {
      const previousDuration = toolDurationSeconds(previous.msg);
      const currentDuration = toolDurationSeconds(msg);
      const combinedDuration =
        previousDuration !== undefined || currentDuration !== undefined
          ? (previousDuration ?? 0) + (currentDuration ?? 0)
          : undefined;

      collapsed[collapsed.length - 1] = {
        msg: {
          ...msg,
          startedAt: previous.msg.startedAt ?? msg.startedAt,
          durationSeconds: combinedDuration,
        },
        repeatCount: previous.repeatCount + 1,
        id: previous.id,
      };
      continue;
    }

    collapsed.push({ msg, repeatCount: 0, id: msg.id });
  }

  return collapsed;
}

/** Add the synthetic typing row used before the first assistant token arrives. */
export function appendSyntheticTypingRow(
  items: CollapsedMessageItem[],
  messages: ChatMessage[],
  streaming: boolean,
): CollapsedItem[] {
  if (!streaming) return items;

  const last = messages[messages.length - 1];
  const isAlreadyStreamingAssistant =
    last?.role === "assistant" && (last.streaming || !last.content);
  if (isAlreadyStreamingAssistant) return items;

  return [...items, { msg: null, id: "typing" }];
}

/** Derive the rows rendered by the thread, including the optional typing row. */
export function deriveCollapsedMessages(
  messages: ChatMessage[],
  streaming: boolean,
): CollapsedItem[] {
  return appendSyntheticTypingRow(
    collapseConsecutiveToolCalls(messages),
    messages,
    streaming,
  );
}

/** Return visible characters for the latest streaming assistant row. */
export function streamingAssistantVisibleChars(messages: ChatMessage[]): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message.role === "assistant" && message.streaming) return message.content.length;
  }
  return 0;
}

/** Return the collapsed-row index of the latest streaming assistant, or -1. */
export function findLiveRowIndex(items: readonly CollapsedItem[]): number {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const message = items[index]?.msg;
    if (message?.role === "assistant" && message.streaming) return index;
  }
  return -1;
}

/** Convert collapsed rows to the existing lightweight minimap contract. */
export function deriveTimelineItems(items: readonly CollapsedItem[]): TimelineMinimapItem[] {
  const sources: TimelineSourceItem[] = items.map((item, index) => {
    if (item.msg === null) {
      return { id: item.id, index, role: "typing", streaming: true };
    }

    const message = item.msg;
    if (message.role === "tool") {
      return {
        id: item.id,
        index,
        role: "tool",
        done: message.done,
        resultTruncated: message.resultTruncated,
        hasError:
          typeof message.result === "string" &&
          /\b(error|failed|traceback)\b/i.test(message.result),
      };
    }

    return {
      id: item.id,
      index,
      role: message.role === "feedback_form" ? "feedback" : message.role,
      streaming: message.role === "assistant" ? message.streaming : false,
    };
  });

  return buildTimelineMinimapItems(sources);
}
