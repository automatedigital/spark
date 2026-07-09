import { useEffect, useRef, useCallback } from "react";
import { sseUrl } from "@/lib/api";

/** SSE envelope from GET /api/events */
export interface SparkEventEnvelope {
  topic: string;
  session_id?: string | null;
  ts: number;
  data: Record<string, unknown>;
}

type Listener = (env: SparkEventEnvelope) => void;

const listeners = new Set<Listener>();
let source: EventSource | null = null;
let reconnectAttempt = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
// True once a connection has dropped, so the next successful open can notify
// listeners that they may have missed events during the gap.
let wasDisconnected = false;
const topicsParam = "sessions,chat,bus,workspace,canvas,skills,memory,notifications";

/**
 * Synthetic topic emitted (not from the server) when the SSE connection
 * re-opens after an error. Listeners use it to re-sync state that may have
 * changed while the bus was disconnected (e.g. a chat turn that finished
 * during the gap, whose `chat.turn_done` event was lost).
 */
export const BUS_RECONNECTED_TOPIC = "bus.reconnected";
export const BUS_GAP_TOPIC = "bus.gap";

function notifyListeners(env: SparkEventEnvelope) {
  listeners.forEach((fn) => {
    try {
      fn(env);
    } catch {
      /* ignore */
    }
  });
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  const delay = Math.min(30_000, 1000 * 2 ** reconnectAttempt) * (0.8 + Math.random() * 0.4);
  reconnectAttempt += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectEventSource();
  }, delay);
}

function connectEventSource() {
  if (typeof window === "undefined") return;
  if (source?.readyState === EventSource.OPEN) return;

  source?.close();
  const url = sseUrl(`/api/events?topics=${encodeURIComponent(topicsParam)}`);
  const es = new EventSource(url);
  source = es;

  es.onopen = () => {
    reconnectAttempt = 0;
    if (wasDisconnected) {
      wasDisconnected = false;
      notifyListeners({
        topic: BUS_RECONNECTED_TOPIC,
        session_id: null,
        ts: Date.now(),
        data: {},
      });
    }
  };

  es.onmessage = (ev) => {
    try {
      const parsed = JSON.parse(ev.data) as SparkEventEnvelope;
      if (parsed?.topic) {
        reconnectAttempt = 0;
        notifyListeners(parsed);
      }
    } catch {
      /* ignore */
    }
  };

  es.onerror = () => {
    es.close();
    source = null;
    wasDisconnected = true;
    scheduleReconnect();
  };
}

/** Subscribe to the shared SSE bus (one connection per tab). */
export function useEventBus(listener: Listener) {
  const listenerRef = useRef(listener);
  listenerRef.current = listener;

  const stableListener = useCallback((env: SparkEventEnvelope) => {
    listenerRef.current(env);
  }, []);

  useEffect(() => {
    connectEventSource();
    listeners.add(stableListener);
    return () => {
      listeners.delete(stableListener);
      if (listeners.size === 0) {
        source?.close();
        source = null;
        if (reconnectTimer) {
          clearTimeout(reconnectTimer);
          reconnectTimer = null;
        }
      }
    };
  }, [stableListener]);
}
