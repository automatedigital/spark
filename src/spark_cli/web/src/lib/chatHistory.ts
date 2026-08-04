import type { ChatMessage } from "./chatTranscriptMerge";

export interface EarlierHistoryRequest {
  sessionId: string;
  limit: number;
  beforeId?: string;
}

export function earlierHistoryRequest(input: {
  sessionId: string | null | undefined;
  loadingEarlier: boolean;
  messages: ChatMessage[];
  limit: number;
}): EarlierHistoryRequest | null {
  if (!input.sessionId || input.loadingEarlier) return null;

  const firstPersistedMessage = input.messages.find(
    (message) => message.role === "user" && typeof message.sessionIdx === "number",
  );
  const firstId = firstPersistedMessage?.id;
  const beforeId = firstId?.startsWith("db:") ? firstId.slice(3) : firstId;

  return {
    sessionId: input.sessionId,
    limit: input.limit,
    ...(beforeId ? { beforeId } : {}),
  };
}

export function prependEarlierMessages(
  current: ChatMessage[],
  earlier: ChatMessage[],
): ChatMessage[] {
  const seenIds = new Set(current.map((message) => message.id));
  const uniqueEarlier = earlier.filter((message) => {
    if (seenIds.has(message.id)) return false;
    seenIds.add(message.id);
    return true;
  });

  return uniqueEarlier.length > 0 ? [...uniqueEarlier, ...current] : current;
}

export function hasEarlierFromResponse(value: boolean | null | undefined): boolean {
  return value ?? false;
}

export function isCurrentSessionResponse(
  responseSequence: number,
  currentSequence: number,
  activeSessionId: string | null,
  activeSessionAliases: ReadonlySet<string>,
  ...sessionIds: Array<string | null | undefined>
): boolean {
  if (responseSequence !== currentSequence) return false;
  if (!activeSessionId) return false;

  return sessionIds.some((id) => id === activeSessionId)
    || sessionIds.some((id) => typeof id === "string" && activeSessionAliases.has(id));
}
