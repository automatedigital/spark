import type { ChatSubagentEventData, SubagentEvent, SubagentRun, SubagentStatus } from "@/lib/api";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled", "interrupted"]);
const STATUS_RANK: Record<string, number> = {
  queued: 1,
  starting: 2,
  running: 3,
  stale: 3,
  completed: 4,
  cancelled: 4,
  interrupted: 4,
  failed: 5,
};

const GLYPHS = ["A", "B", "C", "D", "E", "F", "G", "H"];

const NAMES = [
  "Ampere",
  "Cicero",
  "Curie",
  "Darwin",
  "Euclid",
  "Faraday",
  "Galileo",
  "Hopper",
  "Kepler",
  "Lovelace",
  "Maxwell",
  "Newton",
  "Noether",
  "Pascal",
  "Turing",
  "Vega",
];

const COLORS = [
  { accent: "#7dd3fc", bg: "color-mix(in srgb, #7dd3fc 16%, transparent)", fg: "#bae6fd" },
  { accent: "#86efac", bg: "color-mix(in srgb, #86efac 16%, transparent)", fg: "#bbf7d0" },
  { accent: "#fbbf24", bg: "color-mix(in srgb, #fbbf24 16%, transparent)", fg: "#fde68a" },
  { accent: "#f0abfc", bg: "color-mix(in srgb, #f0abfc 16%, transparent)", fg: "#f5d0fe" },
  { accent: "#fda4af", bg: "color-mix(in srgb, #fda4af 16%, transparent)", fg: "#fecdd3" },
  { accent: "#a5b4fc", bg: "color-mix(in srgb, #a5b4fc 16%, transparent)", fg: "#c7d2fe" },
  { accent: "#5eead4", bg: "color-mix(in srgb, #5eead4 16%, transparent)", fg: "#99f6e4" },
  { accent: "#fdba74", bg: "color-mix(in srgb, #fdba74 16%, transparent)", fg: "#fed7aa" },
];

export interface SubagentVisual {
  glyph: string;
  accent: string;
  bg: string;
  fg: string;
}

function hashString(value: string): number {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function firstString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

export function subagentRunId(run: Partial<SubagentRun> | ChatSubagentEventData): string | null {
  return firstString(run.id, run.run_id, run.subagent_id, run.child_session_id);
}

export function subagentEventRunId(event: SubagentEvent | ChatSubagentEventData): string | null {
  return firstString(event.run_id, event.subagent_id, event.id);
}

export function subagentTimestamp(value: Partial<SubagentRun> | SubagentEvent): number {
  return firstNumber(value.started_at, value.updated_at, value.ended_at, value.ts, value.timestamp, value.created_at) ?? 0;
}

export function subagentVisual(id: string): SubagentVisual {
  const hash = hashString(id);
  return {
    glyph: GLYPHS[hash % GLYPHS.length],
    ...COLORS[hash % COLORS.length],
  };
}

export function subagentDisplayName(run: SubagentRun, index: number): string {
  const name = firstString(run.name, run.metadata?.name);
  if (name && !/^Subagent\s+\d+$/i.test(name)) return name;
  const id = subagentRunId(run) ?? String(index);
  return NAMES[hashString(id) % NAMES.length];
}

export function isSubagentRunning(status: SubagentStatus | null | undefined): boolean {
  return Boolean(status && !TERMINAL_STATUSES.has(status));
}

function normalizeStatus(status: unknown, fallback: SubagentStatus = "running"): SubagentStatus {
  return typeof status === "string" && status.trim() ? status.trim() : fallback;
}

function statusFromTopic(topic: string, data: ChatSubagentEventData): SubagentStatus {
  if (typeof data.status === "string" && data.status.trim()) return data.status.trim();
  if (topic.endsWith(".queued")) return "queued";
  if (topic.endsWith(".started") || topic.endsWith(".start")) return "running";
  if (topic.endsWith(".completed") || topic.endsWith(".done")) return "completed";
  if (topic.endsWith(".failed") || topic.endsWith(".error")) return "failed";
  if (topic.endsWith(".cancelled") || topic.endsWith(".canceled")) return "cancelled";
  if (topic.endsWith(".interrupted")) return "interrupted";
  return "running";
}

function normalizeEvent(event: SubagentEvent, fallbackType: string): SubagentEvent {
  const eventData = asRecord(event.data);
  const payload = asRecord(eventData?.payload);
  const type = firstString(event.type, event.kind, event.event_type, eventData?.event) ?? fallbackType;
  const text = firstString(
    event.text,
    event.content,
    event.message,
    payload?.preview,
    payload?.summary,
    payload?.error,
    payload?.tool,
  );
  const toolName = firstString(event.tool_name, payload?.tool);
  return {
    ...event,
    type,
    run_id: firstString(event.run_id, eventData?.run_id, eventData?.id) ?? event.run_id,
    subagent_id: firstString(event.subagent_id, eventData?.subagent_id) ?? event.subagent_id,
    tool_name: toolName ?? event.tool_name,
    ts: firstNumber(event.ts, event.timestamp) ?? event.ts,
    ...(text ? { text } : {}),
  };
}

function eventKey(event: SubagentEvent): string {
  const id = firstString(event.id, event.tool_call_id);
  if (id) return `id:${id}`;
  return [
    subagentTimestamp(event),
    firstString(event.type, event.kind, event.role) ?? "",
    firstString(event.text, event.content, event.message, event.status) ?? "",
  ].join("|");
}

function mergeEvents(current: SubagentEvent[] = [], incoming: SubagentEvent[] = []): SubagentEvent[] {
  if (incoming.length === 0) return current;
  const byKey = new Map<string, SubagentEvent>();
  for (const event of current) byKey.set(eventKey(event), event);
  for (const event of incoming) {
    const normalized = normalizeEvent(event, "event");
    byKey.set(eventKey(normalized), { ...byKey.get(eventKey(normalized)), ...normalized });
  }
  return Array.from(byKey.values()).sort((a, b) => {
    const delta = subagentTimestamp(a) - subagentTimestamp(b);
    if (delta !== 0) return delta;
    return eventKey(a).localeCompare(eventKey(b));
  });
}

export function normalizeSubagentRun(raw: SubagentRun): SubagentRun | null {
  const id = subagentRunId(raw);
  if (!id) return null;
  const transcript = [...(raw.transcript ?? []), ...(raw.events ?? [])].map((event) =>
    normalizeEvent(event, "event"),
  );
  return {
    ...raw,
    id,
    status: normalizeStatus(raw.status),
    task: firstString(raw.task, raw.goal) ?? raw.task ?? raw.goal ?? null,
    events: mergeEvents([], transcript),
  };
}

function mergeRun(existing: SubagentRun | undefined, incoming: SubagentRun): SubagentRun {
  const startedAt = incoming.started_at ?? existing?.started_at ?? null;
  const endedAt = incoming.ended_at ?? existing?.ended_at ?? null;
  const updatedAt = incoming.updated_at ?? incoming.ended_at ?? incoming.started_at ?? existing?.updated_at ?? null;
  const status = chooseStatus(existing, incoming, updatedAt);
  return {
    ...(existing ?? incoming),
    ...incoming,
    status,
    started_at: startedAt,
    updated_at: updatedAt,
    ended_at: endedAt,
    name: incoming.name ?? existing?.name ?? null,
    task: incoming.task ?? incoming.goal ?? existing?.task ?? existing?.goal ?? null,
    summary: incoming.summary ?? existing?.summary ?? null,
    error: incoming.error ?? existing?.error ?? null,
    events: mergeEvents(existing?.events, incoming.events),
  };
}

function chooseStatus(
  existing: SubagentRun | undefined,
  incoming: SubagentRun,
  incomingUpdatedAt: number | null,
): SubagentStatus {
  if (!existing?.status) return incoming.status;
  if (!incoming.status) return existing.status;

  const existingTerminal = TERMINAL_STATUSES.has(existing.status);
  const incomingTerminal = TERMINAL_STATUSES.has(incoming.status);
  if (existingTerminal && !incomingTerminal) return existing.status;
  if (incomingTerminal && !existingTerminal) return incoming.status;

  const existingUpdatedAt = existing.updated_at ?? existing.ended_at ?? existing.started_at ?? 0;
  const incomingTime = incomingUpdatedAt ?? 0;
  if (incomingTime && existingUpdatedAt && incomingTime < existingUpdatedAt) {
    const existingRank = STATUS_RANK[existing.status] ?? 0;
    const incomingRank = STATUS_RANK[incoming.status] ?? 0;
    return incomingRank > existingRank ? incoming.status : existing.status;
  }
  return incoming.status;
}

export function sortSubagents(runs: SubagentRun[]): SubagentRun[] {
  return [...runs].sort((a, b) => {
    const aStarted = a.started_at ?? a.updated_at ?? 0;
    const bStarted = b.started_at ?? b.updated_at ?? 0;
    if (aStarted !== bStarted) return aStarted - bStarted;
    return a.id.localeCompare(b.id);
  });
}

export function mergeSubagentSnapshot(current: SubagentRun[], snapshot: SubagentRun[]): SubagentRun[] {
  const byId = new Map(current.map((run) => [run.id, run]));
  for (const raw of snapshot) {
    const normalized = normalizeSubagentRun(raw);
    if (!normalized) continue;
    byId.set(normalized.id, mergeRun(byId.get(normalized.id), normalized));
  }
  return sortSubagents(Array.from(byId.values()));
}

function eventFromLiveData(topic: string, data: ChatSubagentEventData): SubagentEvent | null {
  if (data.event) return normalizeEvent(data.event, topic.split(".").pop() ?? "event");
  const text = firstString(data.text, data.content, data.message, data.summary, data.error);
  const type = topic.split(".").pop() ?? "event";
  if (!text && !data.tool_name && !data.status) return null;
  return normalizeEvent(
    {
      type,
      text,
      status: data.status,
      tool_name: firstString(data.tool_name),
      ts: firstNumber(data.ts, data.timestamp, data.updated_at, data.started_at, data.ended_at) ?? Date.now() / 1000,
      data: asRecord(data.data),
    },
    type,
  );
}

export function mergeSubagentLiveEvent(
  current: SubagentRun[],
  topic: string,
  data: ChatSubagentEventData,
): SubagentRun[] {
  const id = subagentRunId(data) ?? subagentEventRunId(data.event ?? data);
  if (!id) return current;

  const existing = current.find((run) => run.id === id);
  const status = statusFromTopic(topic, data);
  const now = Date.now() / 1000;
  const event = eventFromLiveData(topic, data);
  const incoming = normalizeSubagentRun({
    ...(existing ?? {}),
    ...data,
    id,
    status,
    started_at: data.started_at ?? existing?.started_at ?? now,
    updated_at: data.updated_at ?? data.ended_at ?? now,
    ended_at: data.ended_at ?? (TERMINAL_STATUSES.has(status) ? now : existing?.ended_at ?? null),
    task: firstString(data.task, data.goal) ?? existing?.task ?? null,
    events: mergeEvents(data.events ?? data.transcript ?? [], event ? [event] : []),
  } as SubagentRun);

  if (!incoming) return current;
  const byId = new Map(current.map((run) => [run.id, run]));
  byId.set(id, mergeRun(existing, incoming));
  return sortSubagents(Array.from(byId.values()));
}

export function mergeSubagentLiveEvents(
  current: SubagentRun[],
  events: Array<{ topic: string; data: ChatSubagentEventData }>,
): SubagentRun[] {
  return events.reduce(
    (runs, event) => mergeSubagentLiveEvent(runs, event.topic, event.data),
    current,
  );
}

export function preserveSelectedSubagentId(selectedId: string | null, runs: SubagentRun[]): string | null {
  if (!selectedId) return null;
  return runs.some((run) => run.id === selectedId) ? selectedId : null;
}
