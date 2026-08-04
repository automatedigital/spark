import type { SessionMessage } from "@/lib/api";
import type { ChatMessage } from "@/lib/chatTranscriptMerge";
import { boundText, COMPLETED_TEXT_WINDOW_CHARS, REASONING_WINDOW_CHARS } from "@/lib/textWindow";

export interface ChatForkInfo {
  parentSessionId: string | null;
  parentTitle: string | null;
  forkCount: number;
}
export const HISTORY_CHAT_ROLES = new Set<SessionMessage["role"]>(["user", "assistant", "tool"]);

export function chatMessagesFromSession(messages: SessionMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  const toolCallNames: Record<string, string> = {};

  for (const message of messages) {
    if (message.role === "assistant" && message.tool_calls) {
      for (const toolCall of message.tool_calls) {
        if (toolCall.id && toolCall.function?.name) toolCallNames[toolCall.id] = toolCall.function.name;
      }
    }
  }

  messages.forEach((message, index) => {
    const baseId = message.id ? `db:${message.id}` : `db:${message.role}:${index}`;
    if (message.role === "user") {
      if ((message.content ?? "").startsWith("[System:")) return;
      out.push({
        id: baseId,
        role: "user",
        content: message.content ?? "",
        sessionIdx: message.message_index ?? index,
      });
    } else if (message.role === "assistant") {
      const reasoning = message.reasoning?.trim();
      if (reasoning) {
        const bounded = boundText(reasoning, REASONING_WINDOW_CHARS);
        out.push({
          id: `${baseId}:reasoning`,
          role: "reasoning",
          text: bounded.text,
          totalChars: bounded.totalChars,
          omittedChars: bounded.omittedChars,
        });
      }
      if (message.content) {
        const bounded = boundText(message.content, COMPLETED_TEXT_WINDOW_CHARS);
        out.push({
          id: baseId,
          role: "assistant",
          content: bounded.text,
          liveTotalChars: bounded.totalChars,
          liveOmittedChars: bounded.omittedChars,
        });
      }
    } else if (message.role === "tool") {
      const toolId = message.tool_call_id ?? "";
      out.push({
        id: toolId ? `tool:${toolId}` : baseId,
        role: "tool",
        toolId,
        name: message.tool_name ?? toolCallNames[toolId] ?? "tool",
        args: {},
        result: String(message.result_preview ?? message.content ?? ""),
        resultTruncated: Boolean(message.result_truncated ?? message.has_full_result) || undefined,
        done: true,
      });
    }
  });

  return out;
}

export function chatMessagesFromHistory(messages: SessionMessage[]): ChatMessage[] {
  return chatMessagesFromSession(messages.filter((message) => HISTORY_CHAT_ROLES.has(message.role)));
}

export function latestAssistantContentLength(messages: ChatMessage[]): number {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role === "assistant" && message.content) {
      return message.liveTotalChars ?? message.content.length;
    }
  }
  return 0;
}

export function forkInfoFromResponse(response: {
  parent_session_id: string | null;
  parent_title: string | null;
  fork_count: number;
}): ChatForkInfo {
  return {
    parentSessionId: response.parent_session_id,
    parentTitle: response.parent_title,
    forkCount: response.fork_count,
  };
}
