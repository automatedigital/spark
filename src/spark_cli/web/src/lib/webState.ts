import type { PaginatedSessions, SessionInfo, SessionMessage } from "@/lib/api";

export const WEB_STATE_SCHEMA_VERSION = 1 as const;
export const WEB_STATE_PROJECTION_VERSION = 1 as const;
export const DETAIL_IDLE_TTL_MS = 120_000;
const SETTLED_CACHE_KEY = "spark-web-state-settled-v1";
const pendingSettledWrites = new Map<string, ReturnType<typeof setTimeout>>();

export interface WebStateEventV1 {
  schema_version: typeof WEB_STATE_SCHEMA_VERSION;
  topic: string;
  entity_id: string | null;
  session_id?: string | null;
  sequence: number;
  sequence_start?: number;
  projection_version: typeof WEB_STATE_PROJECTION_VERSION;
  timestamp: number;
  payload: Record<string, unknown>;
  data: Record<string, unknown>;
  server_epoch: string;
}

export interface WebStateSnapshotV1 {
  schema_version: typeof WEB_STATE_SCHEMA_VERSION;
  projection_version: typeof WEB_STATE_PROJECTION_VERSION;
  server_epoch: string;
  sequence: number;
  timestamp: number;
  shells: SessionInfo[];
  detail: {
    session_id: string;
    messages: SessionMessage[];
    turn?: { turn_active?: boolean };
  } | null;
  limits: { sessions: number; messages: number; detail_idle_ttl_ms: number };
}

export function parseWebStateEvent(value: unknown): WebStateEventV1 | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const payload = row.payload ?? row.data;
  if (
    row.schema_version !== WEB_STATE_SCHEMA_VERSION
    || row.projection_version !== WEB_STATE_PROJECTION_VERSION
    || typeof row.topic !== "string"
    || !row.topic
    || typeof row.sequence !== "number"
    || row.sequence < 1
    || typeof row.timestamp !== "number"
    || typeof row.server_epoch !== "string"
    || !payload
    || typeof payload !== "object"
    || Array.isArray(payload)
    || !(row.entity_id === null || typeof row.entity_id === "string")
    || !(row.sequence_start === undefined || (
      typeof row.sequence_start === "number"
      && row.sequence_start >= 1
      && row.sequence_start <= row.sequence
    ))
  ) return null;
  return {
    ...(row as unknown as WebStateEventV1),
    session_id: typeof row.session_id === "string" ? row.session_id : row.entity_id as string | null,
    payload: payload as Record<string, unknown>,
    data: payload as Record<string, unknown>,
  };
}

/** Normalize the compatibility-release SSE envelope without weakening v1 validation. */
export function parseLegacyWebStateEvent(
  value: unknown,
  cursor: { sequence: number; serverEpoch: string },
): WebStateEventV1 | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const payload = row.data;
  if (
    typeof row.topic !== "string"
    || !row.topic
    || !payload
    || typeof payload !== "object"
    || Array.isArray(payload)
    || !(row.session_id === undefined || row.session_id === null || typeof row.session_id === "string")
  ) return null;
  const entityId = typeof row.session_id === "string" ? row.session_id : null;
  const timestamp = typeof row.ts === "number" ? row.ts : Date.now() / 1000;
  return {
    schema_version: 1,
    topic: row.topic,
    entity_id: entityId,
    session_id: entityId,
    sequence: cursor.sequence + 1,
    projection_version: 1,
    timestamp,
    payload: payload as Record<string, unknown>,
    data: payload as Record<string, unknown>,
    server_epoch: cursor.serverEpoch,
  };
}

export function legacySessionSnapshot(
  page: PaginatedSessions,
  serverEpoch: string,
  sequence = 0,
): WebStateSnapshotV1 {
  return {
    schema_version: 1,
    projection_version: 1,
    server_epoch: serverEpoch,
    sequence,
    timestamp: Date.now() / 1000,
    shells: page.sessions.slice(0, 50),
    detail: null,
    limits: { sessions: 50, messages: 200, detail_idle_ttl_ms: DETAIL_IDLE_TTL_MS },
  };
}

export type SequenceDecision = "apply" | "duplicate" | "gap" | "snapshot";

export function sequenceDecision(
  event: WebStateEventV1,
  cursor: { sequence: number; projectionVersion: number; serverEpoch: string },
): SequenceDecision {
  if (
    event.projection_version !== cursor.projectionVersion
    || event.server_epoch !== cursor.serverEpoch
  ) return "snapshot";
  if (event.sequence <= cursor.sequence) return "duplicate";
  const sequenceStart = event.sequence_start ?? event.sequence;
  if (sequenceStart !== cursor.sequence + 1) return "gap";
  return "apply";
}

export interface ThreadDetailState {
  sessionId: string;
  messages: readonly SessionMessage[];
  status: string;
  usage?: Record<string, number>;
  mountedAt: number;
  lastAccessedAt: number;
  settled: boolean;
}

/** Normalized state with structural sharing and bounded unmounted detail. */
export class NormalizedWebState {
  readonly shells = new Map<string, SessionInfo>();
  readonly details = new Map<string, ThreadDetailState>();
  private shellOrder: readonly string[] = [];

  replaceShells(rows: readonly SessionInfo[]): readonly string[] {
    const nextIds = rows.map((row) => row.id);
    rows.forEach((row) => this.upsertShell(row));
    for (const id of this.shells.keys()) {
      if (!nextIds.includes(id)) this.shells.delete(id);
    }
    if (
      nextIds.length !== this.shellOrder.length
      || nextIds.some((id, index) => this.shellOrder[index] !== id)
    ) this.shellOrder = Object.freeze(nextIds);
    return this.shellOrder;
  }

  upsertShell(row: SessionInfo): SessionInfo {
    const previous = this.shells.get(row.id);
    if (previous && shallowEqual(previous, row)) return previous;
    const stable = Object.freeze({ ...previous, ...row });
    this.shells.set(row.id, stable);
    if (!previous) this.shellOrder = Object.freeze([row.id, ...this.shellOrder]);
    return stable;
  }

  removeShell(id: string): void {
    if (!this.shells.delete(id)) return;
    this.shellOrder = Object.freeze(this.shellOrder.filter((candidate) => candidate !== id));
    this.details.delete(id);
  }

  selectShells(): readonly SessionInfo[] {
    return this.shellOrder.flatMap((id) => {
      const row = this.shells.get(id);
      return row ? [row] : [];
    });
  }

  selectShell(id: string): SessionInfo | undefined {
    return this.shells.get(id);
  }

  setDetail(detail: ThreadDetailState): ThreadDetailState {
    const previous = this.details.get(detail.sessionId);
    if (previous && shallowEqual(previous, detail)) return previous;
    const stable = Object.freeze({ ...detail, messages: Object.freeze([...detail.messages]) });
    this.details.set(detail.sessionId, stable);
    return stable;
  }

  touchDetail(id: string, now = Date.now()): void {
    const detail = this.details.get(id);
    if (detail) this.details.set(id, { ...detail, lastAccessedAt: now });
  }

  expireIdleDetails(selectedId: string | null, now = Date.now(), ttlMs = DETAIL_IDLE_TTL_MS): string[] {
    const expired: string[] = [];
    for (const [id, detail] of this.details) {
      if (id !== selectedId && now - detail.lastAccessedAt >= ttlMs) {
        this.details.delete(id);
        expired.push(id);
      }
    }
    return expired;
  }
}

function shallowEqual(a: object, b: object): boolean {
  const aRows = Object.entries(a);
  const bRows = Object.entries(b);
  return aRows.length === bRows.length && aRows.every(([key, value]) => (
    Object.is(value, (b as Record<string, unknown>)[key])
  ));
}

interface SettledCacheEntry {
  sessionId: string;
  messages: SessionMessage[];
  sequence: number;
  savedAt: number;
  settled: true;
}

export function readSettledDetail(sessionId: string): SettledCacheEntry | null {
  try {
    const cache = JSON.parse(localStorage.getItem(SETTLED_CACHE_KEY) ?? "{}") as Record<string, SettledCacheEntry>;
    return cache[sessionId]?.settled ? cache[sessionId] : null;
  } catch {
    localStorage.removeItem(SETTLED_CACHE_KEY);
    return null;
  }
}

/** Active tool/reasoning/token state is never accepted by this persistence boundary. */
export function persistSettledDetail(
  sessionId: string,
  messages: SessionMessage[],
  sequence: number,
  settled: boolean,
): boolean {
  if (!settled) return false;
  try {
    const cache = JSON.parse(localStorage.getItem(SETTLED_CACHE_KEY) ?? "{}") as Record<string, SettledCacheEntry>;
    cache[sessionId] = { sessionId, messages, sequence, savedAt: Date.now(), settled: true };
    const bounded = Object.fromEntries(
      Object.entries(cache)
        .sort(([, a], [, b]) => b.savedAt - a.savedAt)
        .slice(0, 8),
    );
    localStorage.setItem(SETTLED_CACHE_KEY, JSON.stringify(bounded));
    return true;
  } catch {
    return false;
  }
}

/** Coalesce rapid final-history reconciliations into one settled cache write. */
export function schedulePersistSettledDetail(
  sessionId: string,
  messages: SessionMessage[],
  sequence: number,
  settled: boolean,
  debounceMs = 350,
): boolean {
  if (!settled) return false;
  const pending = pendingSettledWrites.get(sessionId);
  if (pending) clearTimeout(pending);
  pendingSettledWrites.set(sessionId, setTimeout(() => {
    pendingSettledWrites.delete(sessionId);
    persistSettledDetail(sessionId, messages, sequence, true);
  }, debounceMs));
  return true;
}

export function clearUnsettledOrInvalidDetailCache(): void {
  pendingSettledWrites.forEach((timer) => clearTimeout(timer));
  pendingSettledWrites.clear();
  try {
    const cache = JSON.parse(localStorage.getItem(SETTLED_CACHE_KEY) ?? "{}") as Record<string, SettledCacheEntry>;
    const settled = Object.fromEntries(Object.entries(cache).filter(([, value]) => value?.settled === true));
    localStorage.setItem(SETTLED_CACHE_KEY, JSON.stringify(settled));
  } catch {
    localStorage.removeItem(SETTLED_CACHE_KEY);
  }
}

export const normalizedWebState = new NormalizedWebState();
