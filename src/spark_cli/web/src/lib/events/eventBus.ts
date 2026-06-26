export interface SparkEventEnvelope {
  topic: string;
  session_id?: string | null;
  ts: number;
  data: Record<string, unknown>;
}

export type SparkEventListener = (env: SparkEventEnvelope) => void;
export type SseUrlBuilder = (path: string) => string;
export type EventSourceFactory = (url: string) => EventSource;

export const BUS_RECONNECTED_TOPIC = "bus.reconnected";

const topicsParam = "sessions,chat,workspace,canvas,skills,memory,notifications";

export function createEventBus(
  sseUrl: SseUrlBuilder,
  eventSourceFactory: EventSourceFactory = (url) => new EventSource(url),
) {
  const listeners = new Set<SparkEventListener>();
  let source: EventSource | null = null;
  let reconnectAttempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let wasDisconnected = false;

  const notifyListeners = (env: SparkEventEnvelope) => {
    listeners.forEach((fn) => {
      try {
        fn(env);
      } catch {
        /* ignore */
      }
    });
  };

  const connectEventSource = () => {
    if (typeof window === "undefined") return;
    if (source?.readyState === EventSource.OPEN) return;

    source?.close();
    const url = sseUrl(`/api/events?topics=${encodeURIComponent(topicsParam)}`);
    const es = eventSourceFactory(url);
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
  };

  const scheduleReconnect = () => {
    if (reconnectTimer) return;
    const delay = Math.min(30_000, 1000 * 2 ** reconnectAttempt) * (0.8 + Math.random() * 0.4);
    reconnectAttempt += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectEventSource();
    }, delay);
  };

  return {
    subscribe(listener: SparkEventListener) {
      connectEventSource();
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) {
          source?.close();
          source = null;
          if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
          }
        }
      };
    },
  };
}
