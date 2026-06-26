import { useCallback, useEffect, useRef } from "react";
import { sseUrl } from "@/lib/api";
import {
  BUS_RECONNECTED_TOPIC,
  createEventBus,
  type SparkEventEnvelope,
  type SparkEventListener,
} from "@/lib/events/eventBus";

export { BUS_RECONNECTED_TOPIC, type SparkEventEnvelope };

const eventBus = createEventBus(sseUrl);

/** Subscribe to the shared SSE bus (one connection per tab). */
export function useEventBus(listener: SparkEventListener) {
  const listenerRef = useRef(listener);
  listenerRef.current = listener;

  const stableListener = useCallback((env: SparkEventEnvelope) => {
    listenerRef.current(env);
  }, []);

  useEffect(() => eventBus.subscribe(stableListener), [stableListener]);
}
