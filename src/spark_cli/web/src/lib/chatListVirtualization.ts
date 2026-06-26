export type VirtualizedChatMessage =
  | { id: string; role: "user"; content: string }
  | { id: string; role: "assistant"; content: string; streaming?: boolean }
  | {
      id: string;
      role: "tool";
      name: string;
      startedAt?: number;
      endedAt?: number;
      durationSeconds?: number;
      [key: string]: unknown;
    }
  | { id: string; role: "reasoning"; [key: string]: unknown }
  | { id: string; role: "approval"; [key: string]: unknown }
  | { id: string; role: "feedback_form"; [key: string]: unknown }
  | { id: string; role: "note"; [key: string]: unknown };

export type CollapsedChatItem<T extends VirtualizedChatMessage = VirtualizedChatMessage> =
  | { msg: T; repeatCount: number; id: string }
  | { msg: null; id: "typing" };

type ToolChatMessage = Extract<VirtualizedChatMessage, { role: "tool" }>;
type RealCollapsedChatItem<T extends VirtualizedChatMessage> = { msg: T; repeatCount: number; id: string };

export function toolDurationSeconds(msg: ToolChatMessage): number | undefined {
  if (typeof msg.durationSeconds === "number") return Math.max(0, msg.durationSeconds);
  if (typeof msg.startedAt === "number" && typeof msg.endedAt === "number") {
    return Math.max(0, msg.endedAt - msg.startedAt);
  }
  return undefined;
}

export function collapseChatMessagesForVirtualizer<T extends VirtualizedChatMessage>(
  messages: T[],
  streaming: boolean,
): CollapsedChatItem<T>[] {
  const collapsed: CollapsedChatItem<T>[] = [];
  for (const msg of messages) {
    const prev = collapsed[collapsed.length - 1];
    if (
      msg.role === "tool" &&
      prev && prev.msg !== null && prev.msg.role === "tool" &&
      msg.name === prev.msg.name
    ) {
      const previousItem = prev as RealCollapsedChatItem<T>;
      const previousTool = previousItem.msg as ToolChatMessage;
      const previousDuration = toolDurationSeconds(previousTool);
      const currentDuration = toolDurationSeconds(msg);
      const combinedDuration =
        previousDuration !== undefined || currentDuration !== undefined
          ? (previousDuration ?? 0) + (currentDuration ?? 0)
          : undefined;
      collapsed[collapsed.length - 1] = {
        msg: {
          ...msg,
          startedAt: previousTool.startedAt ?? msg.startedAt,
          durationSeconds: combinedDuration,
        },
        repeatCount: previousItem.repeatCount + 1,
        id: prev.id,
      };
    } else {
      collapsed.push({ msg, repeatCount: 0, id: msg.id });
    }
  }

  if (streaming) {
    const last = messages[messages.length - 1];
    const isAlreadyStreamingAssistant = last?.role === "assistant" && (last.streaming || !last.content);
    if (!isAlreadyStreamingAssistant) collapsed.push({ msg: null, id: "typing" });
  }
  return collapsed;
}

export function estimateChatRowSize(item: CollapsedChatItem | undefined): number {
  if (!item || item.msg === null) return 56;
  switch (item.msg.role) {
    case "user":
      return 72;
    case "assistant":
      return Math.min(900, Math.max(96, Math.ceil(item.msg.content.length / 95) * 22 + 48));
    case "tool":
    case "reasoning":
      return 44;
    case "approval":
      return 160;
    case "feedback_form":
      return 280;
    case "note":
      return 32;
    default:
      return 80;
  }
}
