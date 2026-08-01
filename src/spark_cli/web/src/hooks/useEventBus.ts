import { useCallback, useEffect, useRef } from "react";
import { getApiBase, getDashboardToken, sseUrl } from "@/lib/api";
import type { PaginatedSessions } from "@/lib/api";
import { recordWebEfficiency } from "@/lib/efficiencyMetrics";
import {
  WEB_STATE_PROJECTION_VERSION,
  legacySessionSnapshot,
  parseLegacyWebStateEvent,
  parseWebStateEvent,
  sequenceDecision,
  type WebStateEventV1,
  type WebStateSnapshotV1,
} from "@/lib/webState";

export type SparkEventEnvelope = WebStateEventV1;
type Listener = (env: SparkEventEnvelope) => void;

const listeners = new Set<Listener>();
const encoder = new TextEncoder();
const CURSOR_KEY = "spark-web-state-cursor-v1";
const topicsParam = "sessions,chat,bus,workspace,canvas,skills,memory,notifications";
const STALE_AFTER_MS = 45_000;
const WATCHDOG_INTERVAL_MS = 10_000;

export const BUS_RECONNECTED_TOPIC = "bus.reconnected";
export const BUS_GAP_TOPIC = "bus.gap";
export const BUS_STALE_TOPIC = "bus.stale";
export const BUS_WAKE_TOPIC = "bus.wake";
export const STATE_SNAPSHOT_TOPIC = "state.snapshot";

interface Cursor {
  sequence: number;
  projectionVersion: number;
  serverEpoch: string;
}

class ConnectionSupervisor {
  private source: EventSource | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private watchdogTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectAttempt = 0;
  private lastEventAt = 0;
  private staleSignalled = false;
  private wasDisconnected = false;
  private running = false;
  // A resume cursor is meaningful only alongside a hydrated projection. A new
  // document has an empty React store even when sessionStorage retained the
  // previous cursor, so it must always start from a bounded snapshot.
  private cursor: Cursor | null = null;
  private selectedSessionId: string | null = null;
  private snapshotRecovery: Promise<void> | null = null;
  private legacyMode = false;

  start(): void {
    if (this.running || typeof window === "undefined") return;
    this.running = true;
    window.addEventListener("online", this.handleWake);
    document.addEventListener("visibilitychange", this.handleVisibility);
    this.watchdogTimer = window.setInterval(this.watchdog, WATCHDOG_INTERVAL_MS);
    void this.bootstrap();
  }

  stop(): void {
    if (!this.running) return;
    this.running = false;
    this.source?.close();
    this.source = null;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.watchdogTimer) clearInterval(this.watchdogTimer);
    this.reconnectTimer = null;
    this.watchdogTimer = null;
    window.removeEventListener("online", this.handleWake);
    document.removeEventListener("visibilitychange", this.handleVisibility);
  }

  selectDetail(sessionId: string | null): void {
    if (this.selectedSessionId === sessionId) return;
    this.selectedSessionId = sessionId;
    if (!this.running) return;
    void this.recoverSnapshot();
  }

  private bootstrap = async (): Promise<void> => {
    if (!this.running) return;
    try {
      await this.fetchSnapshot();
      if (this.running) this.connect();
    } catch {
      this.scheduleReconnect();
    }
  };

  private fetchSnapshot = async (): Promise<void> => {
    const qs = new URLSearchParams({ session_limit: "50", message_limit: "200" });
    if (this.selectedSessionId) qs.set("selected_session_id", this.selectedSessionId);
    let response: WebStateSnapshotV1;
    try {
      response = await this.fetchJson<WebStateSnapshotV1>(`/api/web-state/snapshot?${qs}`);
      if (
        response.schema_version !== 1
        || response.projection_version !== 1
        || !Array.isArray(response.shells)
      ) throw new Error("invalid web state snapshot");
      this.legacyMode = false;
    } catch {
      // One-release rollback boundary: an older sidecar serves the SPA HTML for
      // this unknown route. Hydrate from its bounded sessions endpoint and keep
      // consuming the legacy SSE envelope instead of emptying the inbox.
      const page = await this.fetchJson<PaginatedSessions>(
        "/api/sessions?limit=50&offset=0",
      );
      const epoch = this.cursor?.serverEpoch.startsWith("legacy:")
        ? this.cursor.serverEpoch
        : `legacy:${Date.now()}`;
      response = legacySessionSnapshot(page, epoch, this.cursor?.sequence ?? 0);
      this.legacyMode = true;
    }
    this.cursor = {
      sequence: response.sequence,
      projectionVersion: response.projection_version,
      serverEpoch: response.server_epoch,
    };
    this.writeCursor();
    this.notifySynthetic(STATE_SNAPSHOT_TOPIC, { snapshot: response });
  };

  private fetchDeltas = async (): Promise<void> => {
    if (!this.cursor) return this.fetchSnapshot();
    if (this.legacyMode) return this.fetchSnapshot();
    const qs = new URLSearchParams({
      after_sequence: String(this.cursor.sequence),
      projection_version: String(this.cursor.projectionVersion),
      server_epoch: this.cursor.serverEpoch,
    });
    try {
      const response = await this.fetchJson<{
        events: unknown[];
        requires_snapshot: boolean;
      }>(`/api/web-state/deltas?${qs}`);
      if (response.requires_snapshot) return this.fetchSnapshot();
      for (const value of response.events) this.accept(value);
    } catch {
      await this.fetchSnapshot();
    }
  };

  private connect(): void {
    if (!this.running || !this.cursor || document.visibilityState === "hidden") return;
    if (this.source?.readyState === EventSource.OPEN || this.source?.readyState === EventSource.CONNECTING) return;
    this.source?.close();
    const qs = new URLSearchParams({ topics: topicsParam });
    if (!this.legacyMode) {
      qs.set("after_sequence", String(this.cursor.sequence));
      qs.set("projection_version", String(this.cursor.projectionVersion));
      qs.set("server_epoch", this.cursor.serverEpoch);
      if (this.selectedSessionId) qs.set("detail_session_id", this.selectedSessionId);
    }
    const source = new EventSource(sseUrl(`/api/events?${qs}`));
    this.source = source;
    source.onopen = () => {
      this.reconnectAttempt = 0;
      this.lastEventAt = Date.now();
      this.staleSignalled = false;
      if (this.wasDisconnected) {
        this.wasDisconnected = false;
        recordWebEfficiency("reconnects");
        this.notifySynthetic(BUS_RECONNECTED_TOPIC, {});
      }
    };
    source.onmessage = (event) => {
      recordWebEfficiency("eventPayloads");
      recordWebEfficiency("eventPayloadBytes", encoder.encode(event.data).byteLength);
      try { this.accept(JSON.parse(event.data)); } catch { /* malformed frames are ignored */ }
    };
    source.onerror = () => {
      source.close();
      if (this.source === source) this.source = null;
      this.wasDisconnected = true;
      this.scheduleReconnect();
    };
  }

  private accept(value: unknown): void {
    const event = parseWebStateEvent(value)
      ?? (this.legacyMode && this.cursor ? parseLegacyWebStateEvent(value, this.cursor) : null);
    if (!event || !this.cursor) return;
    const decision = sequenceDecision(event, this.cursor);
    if (decision === "duplicate") return;
    if (decision === "gap" || decision === "snapshot" || event.topic === "bus.snapshot_required") {
      this.notifySynthetic(BUS_GAP_TOPIC, { reason: decision });
      void this.recoverSnapshot();
      return;
    }
    this.cursor.sequence = event.sequence;
    this.lastEventAt = Date.now();
    this.staleSignalled = false;
    this.writeCursor();
    listeners.forEach((listener) => {
      try { listener(event); } catch { /* isolate component listeners */ }
    });
  }

  private notifySynthetic(topic: string, payload: Record<string, unknown>): void {
    const cursor = this.cursor ?? { sequence: 0, projectionVersion: 1, serverEpoch: "local" };
    const event = {
      schema_version: 1,
      topic,
      entity_id: null,
      session_id: null,
      sequence: cursor.sequence,
      projection_version: WEB_STATE_PROJECTION_VERSION,
      timestamp: Date.now() / 1000,
      payload,
      data: payload,
      server_epoch: cursor.serverEpoch,
    } satisfies SparkEventEnvelope;
    listeners.forEach((listener) => listener(event));
  }

  private recoverSnapshot(): Promise<void> {
    if (this.snapshotRecovery) return this.snapshotRecovery;
    this.source?.close();
    this.source = null;
    this.snapshotRecovery = this.fetchSnapshot()
      .then(() => this.connect())
      .catch(() => this.scheduleReconnect())
      .finally(() => { this.snapshotRecovery = null; });
    return this.snapshotRecovery;
  }

  private scheduleReconnect(): void {
    if (!this.running || this.reconnectTimer) return;
    const delay = Math.min(30_000, 1_000 * 2 ** this.reconnectAttempt) * (0.8 + Math.random() * 0.4);
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.fetchDeltas().then(() => this.connect()).catch(() => this.scheduleReconnect());
    }, delay);
  }

  private watchdog = (): void => {
    if (!this.running || document.hidden || !this.lastEventAt) return;
    if (Date.now() - this.lastEventAt < STALE_AFTER_MS || this.staleSignalled) return;
    this.staleSignalled = true;
    this.notifySynthetic(BUS_STALE_TOPIC, {});
    void this.fetchDeltas(); // bounded HTTP probe only after stream staleness
  };

  private handleVisibility = (): void => {
    if (document.hidden) {
      this.source?.close();
      this.source = null;
      return;
    }
    this.handleWake();
  };

  private handleWake = (): void => {
    if (!this.running) return;
    this.notifySynthetic(BUS_WAKE_TOPIC, {});
    void this.fetchDeltas().then(() => this.connect()).catch(() => this.scheduleReconnect());
  };

  private async fetchJson<T>(path: string): Promise<T> {
    const headers = new Headers();
    const token = getDashboardToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await fetch(`${getApiBase()}${path}`, { headers });
    if (!response.ok) throw new Error(`web state ${response.status}`);
    return response.json() as Promise<T>;
  }

  private writeCursor(): void {
    if (this.cursor) sessionStorage.setItem(CURSOR_KEY, JSON.stringify(this.cursor));
  }
}

const supervisor = new ConnectionSupervisor();

export function useEventBus(listener: Listener): void {
  const listenerRef = useRef(listener);
  listenerRef.current = listener;
  const stableListener = useCallback((event: SparkEventEnvelope) => listenerRef.current(event), []);
  useEffect(() => {
    listeners.add(stableListener);
    supervisor.start();
    return () => {
      listeners.delete(stableListener);
      if (listeners.size === 0) supervisor.stop();
    };
  }, [stableListener]);
}

/** Select the only chat-detail entity carried by the shared connection. */
export function useSelectedDetailSubscription(sessionId: string | null): void {
  useEffect(() => {
    supervisor.selectDetail(sessionId);
    return () => supervisor.selectDetail(null);
  }, [sessionId]);
}
