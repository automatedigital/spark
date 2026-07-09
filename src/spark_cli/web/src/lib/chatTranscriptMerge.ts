import type { ContextItem } from "./context";

export type ChatMessage =
  | { id: string; role: "user"; content: string; sessionIdx?: number; contextItems?: ContextItem[]; redirect?: boolean }
  | { id: string; role: "assistant"; content: string; streaming?: boolean; renderRevision?: number; usage?: { totalTokens: number; costUsd?: number } }
  | {
      id: string;
      role: "tool";
      toolId: string;
      name: string;
      args: Record<string, unknown>;
      result?: string;
      resultTruncated?: boolean;
      done?: boolean;
      startedAt?: number;
      endedAt?: number;
      durationSeconds?: number;
    }
  | { id: string; role: "reasoning"; text: string }
  | {
      id: string;
      role: "approval";
      approval: Record<string, unknown>;
      resolved?: boolean;
    }
  | { id: string; role: "note"; text: string }
  | { id: string; role: "feedback_form"; submitted?: boolean };

const hasText = (value: string | null | undefined) => Boolean(value && value.length > 0);

export const localTurnCache = new Map<string, ChatMessage[]>();

function cacheableTranscript(messages: ChatMessage[]): ChatMessage[] {
  return messages
    .filter((msg) => msg.role !== "feedback_form")
    .slice(-300)
    .map((msg) => ({ ...msg }));
}

export function rememberLocalTurn(sessionId: string | null, messages: ChatMessage[]) {
  if (!sessionId) return;
  const transcript = cacheableTranscript(messages);
  if (transcript.some((m) => m.role !== "note")) {
    localTurnCache.set(sessionId, transcript);
  }
}

function cacheKey(msg: ChatMessage): string {
  switch (msg.role) {
    case "user":
      return `user:${msg.content}`;
    case "assistant":
      return `assistant:${msg.content}`;
    case "tool":
      return msg.toolId
        ? `tool:${msg.toolId}`
        : `tool:${msg.name}:${msg.startedAt ?? ""}:${msg.result ?? ""}`;
    case "reasoning":
      return `reasoning:${msg.text}`;
    case "approval":
      return `approval:${JSON.stringify(msg.approval)}`;
    case "note":
      return `note:${msg.text}`;
    case "feedback_form":
      return `feedback:${msg.id}`;
  }
}

function isAssistantDuplicate(
  candidate: Extract<ChatMessage, { role: "assistant" }>,
  existing: ChatMessage[],
): boolean {
  const content = candidate.content.trim();
  if (!content) return false;
  return existing.some((msg) => {
    if (msg.role !== "assistant") return false;
    const other = msg.content.trim();
    if (!other) return false;
    if (content === other) return true;
    return content.startsWith(other) || other.startsWith(content);
  });
}

function latestTextAssistant(messages: ChatMessage[]): Extract<ChatMessage, { role: "assistant" }> | undefined {
  return [...messages]
    .reverse()
    .find((m): m is Extract<ChatMessage, { role: "assistant" }> =>
      m.role === "assistant" && hasText(m.content),
    );
}

function mergeCachedProgress(mapped: ChatMessage[], cached: ChatMessage[]): ChatMessage[] {
  if (cached.length === 0) return mapped;
  if (mapped.length === 0) return cached;

  const seen = new Set(mapped.map(cacheKey));
  const missing = cached.filter((msg) => {
    if (msg.role === "assistant" && isAssistantDuplicate(msg, mapped)) return false;
    const key = cacheKey(msg);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return missing.length > 0 ? [...mapped, ...missing] : mapped;
}

export function mergeSyncedMessages(
  mapped: ChatMessage[],
  prev: ChatMessage[],
  sessionId: string | null,
  options: {
    preferSyncedAssistants?: boolean;
    preserveLocalAssistantPrefix?: boolean;
    syncedComplete?: boolean;
  } = {},
): ChatMessage[] {
  const forms = prev.filter((m) => m.role === "feedback_form");
  const withForms = (messages: ChatMessage[]) => (
    forms.length > 0 ? [...messages, ...forms] : messages
  );
  const cachedTurn = sessionId ? localTurnCache.get(sessionId) ?? [] : [];
  const syncedComplete = options.syncedComplete ?? true;

  if (mapped.length === 0 && prev.length > 0) return withForms(prev);
  if (mapped.length === 0 && cachedTurn.length > 0) return withForms(cachedTurn);

  if (!syncedComplete) {
    const base = prev.length >= cachedTurn.length ? prev : cachedTurn;
    const baseWithoutForms = base.filter((m) => m.role !== "feedback_form");
    if (baseWithoutForms.length > mapped.length) {
      const mappedById = new Map(mapped.map((msg) => [msg.id, msg]));
      const baseIds = new Set(baseWithoutForms.map((msg) => msg.id));
      const updatedBase = baseWithoutForms.map((msg) => mappedById.get(msg.id) ?? msg);
      const missingMapped = mapped.filter((msg) => !baseIds.has(msg.id));
      return withForms([...updatedBase, ...missingMapped]);
    }
  }

  if (
    options.preferSyncedAssistants &&
    syncedComplete &&
    mapped.some((m) => m.role === "assistant" && hasText(m.content))
  ) {
    return withForms(mapped);
  }

  const recoveryByAssistantId = new Map(
    [...prev, ...cachedTurn]
      .filter((m): m is Extract<ChatMessage, { role: "assistant" }> =>
        m.role === "assistant" && hasText(m.content),
      )
      .map((m) => [m.id, m]),
  );
  let preservedLongerAssistant = false;
  const monotonicMapped = mapped.map((msg) => {
    if (msg.role !== "assistant" || !hasText(msg.content)) return msg;
    const recovery = recoveryByAssistantId.get(msg.id);
    if (
      recovery &&
      hasText(recovery.content) &&
      recovery.content.length > msg.content.length &&
      recovery.content.startsWith(msg.content)
    ) {
      preservedLongerAssistant = true;
      return { ...recovery, streaming: false };
    }
    return msg;
  });
  if (preservedLongerAssistant) return withForms(monotonicMapped);

  const recoveryMessages = prev.some((m) => m.role === "assistant" && hasText(m.content)) ? prev : cachedTurn;
  const latestLocalAssistant = latestTextAssistant(recoveryMessages);
  if (!latestLocalAssistant) return withForms(mergeCachedProgress(mapped, cachedTurn));

  const latestMappedAssistant = latestTextAssistant(monotonicMapped);
  if (
    options.preserveLocalAssistantPrefix &&
    !options.preferSyncedAssistants &&
    latestMappedAssistant &&
    latestLocalAssistant.content.length > latestMappedAssistant.content.length &&
    latestLocalAssistant.content.startsWith(latestMappedAssistant.content)
  ) {
    return withForms(monotonicMapped.map((msg) => (
      msg.id === latestMappedAssistant.id
        ? {
            ...latestMappedAssistant,
            content: latestLocalAssistant.content,
            streaming: latestLocalAssistant.streaming ?? true,
            renderRevision: latestLocalAssistant.renderRevision ?? latestMappedAssistant.renderRevision,
          }
        : msg
    )));
  }

  const mappedAssistantIds = new Set(
    monotonicMapped
      .filter((m): m is Extract<ChatMessage, { role: "assistant" }> => m.role === "assistant")
      .map((m) => m.id),
  );
  const mappedAssistantCount = monotonicMapped
    .filter((m): m is Extract<ChatMessage, { role: "assistant" }> => m.role === "assistant")
    .filter((m) => hasText(m.content)).length;
  const recoveryAssistantCount = recoveryMessages.filter(
    (m) => m.role === "assistant" && hasText(m.content),
  ).length;
  if (mappedAssistantIds.has(latestLocalAssistant.id)) return withForms(monotonicMapped);

  if (mappedAssistantCount < recoveryAssistantCount) {
    const missingLocalRows = cachedTurn.filter((msg) => {
      if (msg.role === "assistant") {
        return hasText(msg.content) && !mappedAssistantIds.has(msg.id) && !isAssistantDuplicate(msg, monotonicMapped);
      }
      if (msg.role === "reasoning") {
        return !monotonicMapped.some((m) => m.role === "reasoning" && m.id === msg.id);
      }
      return false;
    });
    return withForms([
      ...monotonicMapped,
      ...(missingLocalRows.length > 0
        ? missingLocalRows.map((msg) => (
            msg.role === "assistant" ? { ...msg, streaming: false } : msg
          ))
        : isAssistantDuplicate(latestLocalAssistant, monotonicMapped)
          ? []
          : [{ ...latestLocalAssistant, streaming: false }]),
    ]);
  }

  return withForms(mergeCachedProgress(monotonicMapped, cachedTurn));
}
