import type { ChatMessage } from "./chatTranscriptMerge";

/** Values accepted from persisted rows and live event metadata. */
export type TimelineTimestamp = number | string | Date;

export interface TimelineUsage {
  totalTokens: number;
  inputTokens?: number;
  outputTokens?: number;
  costUsd?: number;
  model?: string;
}

export interface TimelineChangedFile {
  path: string;
  additions?: number;
  deletions?: number;
  status?: string;
}

export interface TimelineSubagent {
  id: string;
  name?: string;
  task?: string;
  status?: string;
  error?: string;
  startedAt?: TimelineTimestamp;
  endedAt?: TimelineTimestamp;
}

export interface TimelineRequestedInput {
  id?: string;
  prompt: string;
  resolved?: boolean;
}

/** Optional metadata may be attached to any ChatMessage by a live adapter. */
export interface TimelineMessageMetadata {
  turnId?: string | null;
  timestamp?: TimelineTimestamp;
  startedAt?: TimelineTimestamp;
  endedAt?: TimelineTimestamp;
  completedAt?: TimelineTimestamp;
  createdAt?: TimelineTimestamp;
  usage?: TimelineUsage;
  changedFiles?: readonly TimelineChangedFile[];
  changedFile?: TimelineChangedFile;
  subagent?: TimelineSubagent | readonly TimelineSubagent[];
  subagents?: readonly TimelineSubagent[];
  status?: string;
  turnStatus?: string;
  interrupted?: boolean;
  redirect?: boolean;
  error?: string;
  failure?: string | boolean;
  requestedInput?: TimelineRequestedInput;
  activityCount?: number;
}

export type ThreadTimelineMessage = ChatMessage & TimelineMessageMetadata;

export type TimelineTurnStatus =
  | "settled"
  | "active"
  | "interrupted"
  | "failed"
  | "awaiting-approval"
  | "awaiting-input";

export interface TimelineUserMessage {
  readonly id: string;
  readonly content: string;
  readonly sessionIdx?: number;
  readonly redirect: boolean;
  readonly timestamp?: number;
  readonly source: Extract<ThreadTimelineMessage, { role: "user" }>;
}

export interface TimelineAssistantMessage {
  readonly kind: "assistant";
  readonly id: string;
  readonly content: string;
  readonly streaming: boolean;
  readonly timestamp?: number;
  readonly usage?: TimelineUsage;
  readonly source: Extract<ThreadTimelineMessage, { role: "assistant" }>;
}

export interface TimelineReasoningItem {
  readonly kind: "reasoning";
  readonly id: string;
  readonly text: string;
  readonly timestamp?: number;
  readonly sourceMessageIds: readonly string[];
}

export interface TimelineToolItem {
  readonly kind: "tool";
  readonly id: string;
  readonly toolId: string;
  readonly name: string;
  readonly args: Readonly<Record<string, unknown>>;
  readonly result?: string;
  readonly resultTruncated: boolean;
  readonly done: boolean;
  readonly failed: boolean;
  readonly timestamp?: number;
  readonly sourceMessageIds: readonly string[];
}

export interface TimelineApprovalItem {
  readonly kind: "approval";
  readonly id: string;
  readonly approval: Readonly<Record<string, unknown>>;
  readonly resolved: boolean;
  readonly timestamp?: number;
  readonly sourceMessageIds: readonly string[];
}

export interface TimelineSubagentItem {
  readonly kind: "subagent";
  readonly id: string;
  readonly subagent: TimelineSubagent;
  readonly timestamp?: number;
  readonly sourceMessageIds: readonly string[];
}

export interface TimelineRequestedInputItem {
  readonly kind: "requested-input";
  readonly id: string;
  readonly requestedInput: TimelineRequestedInput;
  readonly timestamp?: number;
  readonly sourceMessageIds: readonly string[];
}

export interface TimelineNoteItem {
  readonly kind: "note";
  readonly id: string;
  readonly text: string;
  readonly timestamp?: number;
  readonly sourceMessageIds: readonly string[];
}

export interface TimelineIntermediateAssistantItem {
  readonly kind: "assistant";
  readonly id: string;
  readonly content: string;
  readonly timestamp?: number;
  readonly sourceMessageIds: readonly string[];
}

export interface TimelineFeedbackItem {
  readonly kind: "feedback";
  readonly id: string;
  readonly submitted: boolean;
  readonly timestamp?: number;
  readonly sourceMessageIds: readonly string[];
}

export type TimelineWorkItem =
  | TimelineReasoningItem
  | TimelineToolItem
  | TimelineApprovalItem
  | TimelineSubagentItem
  | TimelineRequestedInputItem
  | TimelineFeedbackItem
  | TimelineNoteItem
  | TimelineIntermediateAssistantItem;

export interface TimelineWorkSummary {
  readonly kind: "work-summary";
  readonly id: string;
  readonly label: string;
  readonly actionCount: number;
  readonly durationMs?: number;
}

export type TimelineVisibleItem =
  | TimelineAssistantMessage
  | TimelineWorkSummary
  | TimelineWorkItem;

export interface TimelineTurnTimestamps {
  readonly startedAt?: number;
  readonly endedAt?: number;
  readonly durationMs?: number;
}

export interface TimelineTurn {
  readonly id: string;
  readonly userMessage?: TimelineUserMessage;
  readonly assistantMessages: readonly TimelineAssistantMessage[];
  readonly intermediateAssistantMessages: readonly TimelineAssistantMessage[];
  readonly finalAnswer?: TimelineAssistantMessage;
  readonly workItems: readonly TimelineWorkItem[];
  readonly subagents: readonly TimelineSubagent[];
  readonly approvals: readonly TimelineApprovalItem[];
  readonly requestedInputs: readonly TimelineRequestedInputItem[];
  readonly changedFiles: readonly TimelineChangedFile[];
  readonly usage?: TimelineUsage;
  readonly timestamps: TimelineTurnTimestamps;
  readonly status: TimelineTurnStatus;
  readonly isSettled: boolean;
  readonly isExpanded: boolean;
  readonly workSummary: TimelineWorkSummary;
  /** Final answer first; forced unresolved/failure items follow the summary. */
  readonly visibleItems: readonly TimelineVisibleItem[];
}

export interface ThreadTimeline {
  readonly turns: readonly TimelineTurn[];
  readonly items: readonly TimelineTurn[];
}

export interface BuildThreadTimelineOptions {
  readonly previous?: ThreadTimeline;
}

interface TurnDraft {
  id: string;
  messages: ThreadTimelineMessage[];
  interrupted: boolean;
}

const turnKeys = new WeakMap<object, string>();
const itemKeys = new WeakMap<object, string>();
const turnSourceMessages = new WeakMap<TimelineTurn, readonly ThreadTimelineMessage[]>();

function normalizeTimestamp(value: TimelineTimestamp | undefined): number | undefined {
  if (value == null) return undefined;
  const numeric = value instanceof Date ? value.getTime() : typeof value === "number" ? value : Date.parse(value);
  if (!Number.isFinite(numeric)) return undefined;
  // Python timestamps and tool timestamps are seconds; browser timestamps are milliseconds.
  return Math.abs(numeric) < 100_000_000_000 ? numeric * 1000 : numeric;
}

function messageTimestamp(message: ThreadTimelineMessage): number | undefined {
  return normalizeTimestamp(
    message.timestamp ?? message.startedAt ?? message.createdAt ?? message.endedAt ?? message.completedAt,
  );
}

function metadataOf(message: ThreadTimelineMessage): TimelineMessageMetadata {
  return message as ThreadTimelineMessage;
}

function explicitTurnId(message: ThreadTimelineMessage): string | undefined {
  const value = metadataOf(message).turnId;
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function canonicalValue(value: unknown): string {
  if (value === undefined) return "undefined";
  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalValue).join(",")}]`;
  if (typeof value === "object") {
    return `{${Object.keys(value as Record<string, unknown>).sort().map((key) => `${JSON.stringify(key)}:${canonicalValue((value as Record<string, unknown>)[key])}`).join(",")}}`;
  }
  return JSON.stringify(String(value));
}

function messageIdentity(message: ThreadTimelineMessage, index: number): string {
  return message.id || `${message.role}:${index}`;
}

function isFailureText(value: string | undefined): boolean {
  if (!value) return false;
  const text = value.trim();
  return Boolean(
    /^(?:error|fatal|failed|failure|traceback|exception)\b/i.test(text) ||
    /\b(?:command|process|task|request|build|test|tool)\s+(?:has\s+)?failed\b/i.test(text) ||
    /\bexit(?:ed)?\s+(?:with\s+)?(?:code\s+)?[1-9]\d*\b/i.test(text),
  );
}

function isInterruptedMessage(message: ThreadTimelineMessage): boolean {
  const metadata = metadataOf(message);
  const status = `${metadata.status ?? ""} ${metadata.turnStatus ?? ""}`.toLowerCase();
  return Boolean(
    metadata.interrupted ||
    metadata.redirect ||
    /\b(interrupted|interrupting|redirected|redirecting|stopping|stopped|cancelled|canceled)\b/.test(status) ||
    (message.role === "note" && /\b(interrupted|redirecting|stopping)\b/i.test(message.text)),
  );
}

function isExplicitFailure(message: ThreadTimelineMessage): boolean {
  const metadata = metadataOf(message);
  const status = `${metadata.status ?? ""} ${metadata.turnStatus ?? ""}`.toLowerCase();
  if (typeof metadata.failure === "boolean") return metadata.failure;
  return Boolean(
    (typeof metadata.failure === "string" && metadata.failure.trim()) ||
    (typeof metadata.error === "string" && metadata.error.trim()) ||
    /\b(failed|failure|error|exception)\b/.test(status),
  );
}

function isActiveStatus(message: ThreadTimelineMessage): boolean {
  const status = `${metadataOf(message).status ?? ""} ${metadataOf(message).turnStatus ?? ""}`.toLowerCase();
  return /\b(active|starting|running|streaming|thinking|pending|working)\b/.test(status);
}

function requestedInputOf(message: ThreadTimelineMessage): TimelineRequestedInput | undefined {
  const input = metadataOf(message).requestedInput;
  if (!input || typeof input.prompt !== "string") return undefined;
  return { ...input, prompt: input.prompt };
}

function subagentsOf(message: ThreadTimelineMessage): TimelineSubagent[] {
  const metadata = metadataOf(message);
  const values = [
    ...(metadata.subagent == null ? [] : Array.isArray(metadata.subagent) ? metadata.subagent : [metadata.subagent]),
    ...(metadata.subagents ?? []),
  ];
  return values.map((subagent, index) => ({
    ...subagent,
    id: subagent.id || `${message.id}:subagent:${index}`,
  }));
}

function changedFilesOf(message: ThreadTimelineMessage): TimelineChangedFile[] {
  const metadata = metadataOf(message);
  return [
    ...(metadata.changedFile ? [metadata.changedFile] : []),
    ...(metadata.changedFiles ?? []),
  ].filter((file) => Boolean(file.path));
}

function messageItems(message: ThreadTimelineMessage, index: number): TimelineWorkItem[] {
  const id = messageIdentity(message, index);
  const timestamp = messageTimestamp(message);
  const sourceMessageIds = [message.id];
  switch (message.role) {
    case "reasoning":
      return [{ kind: "reasoning", id, text: message.text, timestamp, sourceMessageIds }];
    case "tool": {
      const failed = isExplicitFailure(message) || isFailureText(message.result);
      return [{
        kind: "tool",
        id,
        toolId: message.toolId,
        name: message.name,
        args: message.args,
        ...(message.result === undefined ? {} : { result: message.result }),
        resultTruncated: Boolean(message.resultTruncated),
        done: Boolean(message.done ?? message.result !== undefined),
        failed,
        timestamp,
        sourceMessageIds,
      }];
    }
    case "approval":
      return [{ kind: "approval", id, approval: message.approval, resolved: Boolean(message.resolved), timestamp, sourceMessageIds }];
    case "note": {
      return [{ kind: "note", id, text: message.text, timestamp, sourceMessageIds }];
    }
    case "feedback_form":
      return [{ kind: "feedback", id, submitted: Boolean(message.submitted), timestamp, sourceMessageIds }];
    case "assistant":
    case "user":
      return [];
  }
}

function assistantOf(message: Extract<ThreadTimelineMessage, { role: "assistant" }>, index: number): TimelineAssistantMessage {
  const timestamp = messageTimestamp(message);
  return {
    kind: "assistant",
    id: messageIdentity(message, index),
    content: message.content,
    streaming: Boolean(message.streaming),
    ...(timestamp === undefined ? {} : { timestamp }),
    ...(message.usage === undefined ? {} : { usage: { ...message.usage } }),
    source: message,
  };
}

function userOf(message: Extract<ThreadTimelineMessage, { role: "user" }>, index: number): TimelineUserMessage {
  const timestamp = messageTimestamp(message);
  return {
    id: messageIdentity(message, index),
    content: message.content,
    ...(message.sessionIdx === undefined ? {} : { sessionIdx: message.sessionIdx }),
    redirect: Boolean(message.redirect || metadataOf(message).redirect),
    ...(timestamp === undefined ? {} : { timestamp }),
    source: message,
  };
}

function mergeUsage(messages: readonly ThreadTimelineMessage[]): TimelineUsage | undefined {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const usage = metadataOf(messages[index]).usage;
    if (usage) return { ...usage };
  }
  return undefined;
}

function turnTimestamps(messages: readonly ThreadTimelineMessage[]): TimelineTurnTimestamps {
  const starts = messages.flatMap((message) => [
    normalizeTimestamp(metadataOf(message).startedAt),
    messageTimestamp(message),
  ]).filter((value): value is number => value !== undefined);
  const ends = messages.flatMap((message) => [
    normalizeTimestamp(metadataOf(message).endedAt),
    normalizeTimestamp(metadataOf(message).completedAt),
  ]).filter((value): value is number => value !== undefined);
  const startedAt = starts.length ? Math.min(...starts) : undefined;
  const endedAt = ends.length ? Math.max(...ends) : undefined;
  const durationMs = startedAt !== undefined && endedAt !== undefined && endedAt >= startedAt
    ? endedAt - startedAt
    : messages.reduce((total, message) => total + (message.role === "tool" && message.durationSeconds ? message.durationSeconds * 1000 : 0), 0) || undefined;
  return {
    ...(startedAt === undefined ? {} : { startedAt }),
    ...(endedAt === undefined ? {} : { endedAt }),
    ...(durationMs === undefined ? {} : { durationMs }),
  };
}

function actionCount(workItems: readonly TimelineWorkItem[], metadata: readonly ThreadTimelineMessage[]): number {
  const counted = workItems.filter((item) => item.kind === "tool").length;
  return Math.max(counted, ...metadata.map((message) => metadataOf(message).activityCount ?? 0), 0);
}

function formatDuration(durationMs: number | undefined): string | undefined {
  if (durationMs === undefined || durationMs <= 0) return undefined;
  let seconds = Math.round(durationMs / 1000);
  const hours = Math.floor(seconds / 3600);
  seconds %= 3600;
  const minutes = Math.floor(seconds / 60);
  seconds %= 60;
  const parts: string[] = [];
  if (hours) parts.push(`${hours}h`);
  if (minutes || hours) parts.push(`${minutes}m`);
  if (seconds || parts.length === 0) parts.push(`${seconds}s`);
  return parts.join(" ");
}

function itemSignature(item: object): string {
  const existing = itemKeys.get(item);
  if (existing) return existing;
  const signature = canonicalValue(item);
  itemKeys.set(item, signature);
  return signature;
}

function reuseItem<T extends object>(previous: T | undefined, candidate: T): T {
  const same = previous && itemSignature(previous) === itemSignature(candidate);
  return same ? previous : candidate;
}

function reuseArray<T extends object>(previous: readonly T[] | undefined, candidates: readonly T[]): readonly T[] {
  if (!previous) return candidates;
  const byId = new Map<string, T>();
  for (const item of previous) {
    const id = (item as { id?: string }).id;
    if (id) byId.set(id, item);
  }
  let changed = previous.length !== candidates.length;
  const next = candidates.map((candidate) => {
    const previousItem = byId.get((candidate as { id?: string }).id ?? "");
    const reused = reuseItem(previousItem, candidate);
    if (reused === candidate) changed = true;
    return reused;
  });
  return changed ? next : previous;
}

function statusOf(
  messages: readonly ThreadTimelineMessage[],
  workItems: readonly TimelineWorkItem[],
  _subagents: readonly TimelineSubagent[],
  approvals: readonly TimelineApprovalItem[],
  requestedInputs: readonly TimelineRequestedInputItem[],
  interrupted: boolean,
): TimelineTurnStatus {
  const statusText = messages.map((message) => `${metadataOf(message).status ?? ""} ${metadataOf(message).turnStatus ?? ""}`).join(" ").toLowerCase();
  if (
    workItems.some((item) => item.kind === "feedback" && !item.submitted) ||
    requestedInputs.some((item) => !item.requestedInput.resolved) ||
    /\b(awaiting[ _-]?input|requested[ _-]?input)\b/.test(statusText)
  ) return "awaiting-input";
  if (
    approvals.some((item) => !item.resolved) ||
    /\b(awaiting[ _-]?approval|approval[ _-]?requested)\b/.test(statusText)
  ) return "awaiting-approval";
  if (interrupted || messages.some(isInterruptedMessage)) return "interrupted";
  if (
    workItems.some((item) => item.kind === "tool" && item.failed) ||
    messages.some(isExplicitFailure)
  ) return "failed";
  if (
    messages.some((message) => message.role === "assistant" && message.streaming) ||
    workItems.some((item) => item.kind === "tool" && !item.done) ||
    messages.some(isActiveStatus)
  ) return "active";
  return "settled";
}

function turnSignature(turn: TimelineTurn): string {
  return canonicalValue({
    id: turn.id,
    user: turn.userMessage,
    assistants: turn.assistantMessages,
    work: turn.workItems,
    subagents: turn.subagents,
    approvals: turn.approvals,
    requestedInputs: turn.requestedInputs,
    changedFiles: turn.changedFiles,
    usage: turn.usage,
    timestamps: turn.timestamps,
    status: turn.status,
    expanded: turn.isExpanded,
    summary: turn.workSummary,
    visible: turn.visibleItems,
  });
}

function buildDrafts(messages: readonly ThreadTimelineMessage[]): TurnDraft[] {
  const drafts: TurnDraft[] = [];
  const byExplicitId = new Map<string, TurnDraft>();
  let current: TurnDraft | undefined;
  let orphanCount = 0;
  let userCount = 0;

  messages.forEach((message, index) => {
    const explicit = explicitTurnId(message);
    if (message.role === "user" && message.redirect && current) {
      current.interrupted = true;
    }

    let draft = explicit ? byExplicitId.get(explicit) : undefined;
    if (!draft && message.role === "user") {
      userCount += 1;
      draft = { id: explicit ? `turn:${explicit}` : `turn:user:${message.id || message.sessionIdx || userCount}`, messages: [], interrupted: false };
      drafts.push(draft);
      if (explicit) byExplicitId.set(explicit, draft);
    }
    if (!draft) {
      if (explicit) {
        draft = { id: `turn:${explicit}`, messages: [], interrupted: false };
        drafts.push(draft);
        byExplicitId.set(explicit, draft);
      } else if (current) {
        draft = current;
      } else {
        draft = { id: `turn:orphan:${orphanCount++}`, messages: [], interrupted: false };
        drafts.push(draft);
      }
    }
    draft.messages.push(message);
    if (isInterruptedMessage(message)) draft.interrupted = true;
    current = draft;
    void index;
  });
  return drafts;
}

function buildTurn(draft: TurnDraft, previous: TimelineTurn | undefined): TimelineTurn {
  const messages = draft.messages;
  const previousSources = previous ? turnSourceMessages.get(previous) : undefined;
  if (
    previous
    && previousSources?.length === messages.length
    && messages.every((message, index) => message === previousSources[index])
  ) {
    return previous;
  }
  const userMessage = messages.find((message): message is Extract<ThreadTimelineMessage, { role: "user" }> => message.role === "user");
  const assistantMessages = messages
    .map((message, index) => message.role === "assistant" ? assistantOf(message, index) : undefined)
    .filter((message): message is TimelineAssistantMessage => message !== undefined);
  const finalAnswer = assistantMessages.at(-1);
  const intermediateAssistantMessages = finalAnswer ? assistantMessages.slice(0, -1) : assistantMessages;
  const workItems = messages.flatMap((message, index) => messageItems(message, index))
    .filter((item) => item.kind !== "subagent");
  const requestedInputItems: TimelineRequestedInputItem[] = messages.flatMap((message, index) => {
    const requestedInput = requestedInputOf(message);
    if (!requestedInput) return [];
    return [{
      kind: "requested-input" as const,
      id: `${messageIdentity(message, index)}:requested-input`,
      requestedInput,
      timestamp: messageTimestamp(message),
      sourceMessageIds: [message.id],
    }];
  });
  const subagents = messages.flatMap(subagentsOf);
  const allWorkItems = [...workItems, ...requestedInputItems, ...intermediateAssistantMessages.map((assistant) => ({
    kind: "assistant" as const,
    id: `${draft.id}:assistant:${assistant.id}`,
    content: assistant.content,
    ...(assistant.timestamp === undefined ? {} : { timestamp: assistant.timestamp }),
    sourceMessageIds: [assistant.id],
  }))];
  const approvals = allWorkItems.filter((item): item is TimelineApprovalItem => item.kind === "approval");
  const requestedInputs = allWorkItems.filter((item): item is TimelineRequestedInputItem => item.kind === "requested-input");
  const changedByPath = new Map<string, TimelineChangedFile>();
  for (const message of messages) {
    for (const file of changedFilesOf(message)) {
      changedByPath.set(file.path, { ...(changedByPath.get(file.path) ?? {}), ...file });
    }
  }
  const changedFiles = [...changedByPath.values()];
  const timestamps = turnTimestamps(messages);
  const status = statusOf(messages, allWorkItems, subagents, approvals, requestedInputs, draft.interrupted);
  const isSettled = status === "settled";
  const isExpanded = !isSettled;
  const count = actionCount(allWorkItems, messages);
  const duration = formatDuration(timestamps.durationMs);
  const label = duration ? `Worked for ${duration} · ${count} ${count === 1 ? "action" : "actions"}` : count ? `Worked · ${count} ${count === 1 ? "action" : "actions"}` : "Worked";
  const workSummary: TimelineWorkSummary = {
    kind: "work-summary",
    id: `${draft.id}:work-summary`,
    label,
    actionCount: count,
    ...(timestamps.durationMs === undefined ? {} : { durationMs: timestamps.durationMs }),
  };
  const previousUser = previous?.userMessage;
  const reusedUser = userMessage ? reuseItem(previousUser, userOf(userMessage, messages.indexOf(userMessage))) : undefined;
  const reusedAssistants = reuseArray(previous?.assistantMessages, assistantMessages);
  const reusedIntermediate = reusedAssistants.length > 0 ? reusedAssistants.slice(0, -1) : [];
  const reusedWork = reuseArray(previous?.workItems, allWorkItems);
  const reusedSubagents = reuseArray(previous?.subagents, subagents);
  const reusedApprovals = reusedWork.filter((item): item is TimelineApprovalItem => item.kind === "approval");
  const reusedRequested = reusedWork.filter((item): item is TimelineRequestedInputItem => item.kind === "requested-input");
  const reusedFiles = reuseArray(previous?.changedFiles, changedFiles);
  const reusedFinal = reusedAssistants.at(-1);
  const reusedSummary = reuseItem(previous?.workSummary, workSummary);
  const reusedVisible = reuseArray(previous?.visibleItems, [
    ...(reusedFinal ? [reusedFinal] : []),
    ...(reusedWork.length > 0 ? [reusedSummary] : []),
    ...(isExpanded ? reusedWork : reusedWork.filter((item) => (
      (item.kind === "tool" && item.failed) ||
      (item.kind === "approval" && !item.resolved) ||
      (item.kind === "requested-input" && !item.requestedInput.resolved)
    ))),
  ]);
  const turn: TimelineTurn = {
    id: draft.id,
    ...(reusedUser === undefined ? {} : { userMessage: reusedUser }),
    assistantMessages: reusedAssistants,
    intermediateAssistantMessages: reusedIntermediate,
    ...(reusedFinal === undefined ? {} : { finalAnswer: reusedFinal }),
    workItems: reusedWork,
    subagents: reusedSubagents,
    approvals: reusedApprovals,
    requestedInputs: reusedRequested,
    changedFiles: reusedFiles,
    ...(mergeUsage(messages) === undefined ? {} : { usage: mergeUsage(messages) }),
    timestamps,
    status,
    isSettled,
    isExpanded,
    workSummary: reusedSummary,
    visibleItems: reusedVisible,
  };
  const key = turnSignature(turn);
  turnKeys.set(turn, key);
  const previousKey = previous ? turnKeys.get(previous) : undefined;
  if (previous && previousKey === key) {
    turnSourceMessages.set(previous, messages);
    return previous;
  }
  turnSourceMessages.set(turn, messages);
  return turn;
}

/**
 * Build a deterministic, UI-ready timeline without React, transport, or clock state.
 * Pass the previous result to retain settled turns and unaffected active items by identity.
 */
export function buildThreadTimeline(
  messages: readonly ThreadTimelineMessage[],
  options: BuildThreadTimelineOptions = {},
): ThreadTimeline {
  const previousById = new Map((options.previous?.turns ?? []).map((turn) => [turn.id, turn]));
  const turns = buildDrafts(messages).map((draft) => buildTurn(draft, previousById.get(draft.id)));
  if (options.previous && turns.length === options.previous.turns.length && turns.every((turn, index) => turn === options.previous?.turns[index])) {
    return options.previous;
  }
  return { turns, items: turns };
}

export const deriveThreadTimeline = buildThreadTimeline;
