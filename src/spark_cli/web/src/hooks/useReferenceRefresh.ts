import { useEffect, useRef } from "react";
import { useEventBus } from "./useEventBus";
import { REFERENCE_TTL_MS, referenceResources, type ReferenceResource } from "@/lib/referenceResources";
import { SIDEBAR_SCOPE_EVENT } from "@/lib/sidebarPrefs";

const recoveryTopics = new Set(["bus.reconnected", "bus.gap", "bus.wake"]);
export function useReferenceRefresh(id: ReferenceResource, load: () => void) {
  const latest = useRef(load);
  latest.current = load;
  useEventBus((event) => {
    if (event.topic === "state.snapshot") referenceResources.refresh(id);
    if (recoveryTopics.has(event.topic)
      || (id === "memory" && event.topic === "memory.updated")
      || (id === "cron" && event.topic === "bus.cron_changed")) {
      referenceResources.refresh(id, true);
    }
  });
  useEffect(() => observeReferenceRefresh(id, () => latest.current()), [id]);
}

/** Shared lifecycle, also exercised with a deterministic five-minute clock. */
export function observeReferenceRefresh(id: ReferenceResource, load: () => void) {
  const visible = () => document.visibilityState !== "hidden" && navigator.onLine !== false;
  const refresh = () => { if (visible()) referenceResources.refresh(id); };
  const recover = () => { if (visible()) referenceResources.refresh(id, true); };
  const unsubscribe = referenceResources.subscribe(id, () => { if (visible()) load(); });
  load();
  window.addEventListener("focus", refresh);
  window.addEventListener("online", recover);
  window.addEventListener("storage", recover);
  window.addEventListener(SIDEBAR_SCOPE_EVENT, recover);
  document.addEventListener("visibilitychange", refresh);
  const timer = window.setInterval(refresh, REFERENCE_TTL_MS);
  return () => {
    unsubscribe(); window.clearInterval(timer);
    window.removeEventListener("focus", refresh);
    window.removeEventListener("online", recover);
    window.removeEventListener("storage", recover);
    window.removeEventListener(SIDEBAR_SCOPE_EVENT, recover);
    document.removeEventListener("visibilitychange", refresh);
  };
}
