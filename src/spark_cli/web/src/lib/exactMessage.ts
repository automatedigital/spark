import type { SessionMessage } from "./api";

export function exactAssistantContent(
  messages: SessionMessage[],
  renderedId: string,
): string | null {
  const databaseId = renderedId.startsWith("db:") ? renderedId.slice(3) : renderedId;
  const exact = messages.find((message) => (
    message.role === "assistant" && message.id != null && String(message.id) === databaseId
  ));
  return exact?.content ?? null;
}

export async function copyExactAssistantContent(options: {
  renderedId: string;
  visibleFallback: string;
  loadMessages: () => Promise<SessionMessage[]>;
  writeText: (text: string) => Promise<void>;
}): Promise<string> {
  const messages = await options.loadMessages();
  const content = exactAssistantContent(messages, options.renderedId) ?? options.visibleFallback;
  await options.writeText(content);
  return content;
}
