import { useCallback, useEffect, useState, useRef, useSyncExternalStore, type SetStateAction } from "react";
import { api, getApiBase } from "@/lib/api";
import type { ContextItem } from "@/lib/context";
import { acknowledgeDraft, discardDraft, draftKey, flushDraft, getDraft, resolveDraftConflict, subscribeDraft, updateDraft } from "@/lib/draftStore";

export function useChatDraft(project: string | null, thread: string | null) {
  let backend: string;
  try { backend = getApiBase() || window.location.origin; } catch { backend = window.location.origin; }
  const [identity, setIdentity] = useState<{ backend: string; profile: string } | null>(null);
  useEffect(() => {
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout>;
    const load = () => {
      void api.getStatus().then((status) => {
        if (!cancelled && status.spark_home) setIdentity({ backend, profile: status.spark_home });
      }).catch(() => { if (!cancelled) retry = setTimeout(load, 3000); });
    };
    load();
    return () => { cancelled = true; clearTimeout(retry); };
  }, [backend]);
  const ready = identity?.backend === backend;
  // The pending key is never used for editing or persisted: identity must first
  // be confirmed by this backend, avoiding a previous profile's draft flashing.
  const key = draftKey({ backend, profile: ready ? identity.profile : "pending-identity", project, thread });
  const activeKey = useRef(key);
  activeKey.current = key;
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const isCurrent = useCallback(() => mounted.current && activeKey.current === key, [key]);
  const entry = useSyncExternalStore(subscribeDraft, useCallback(() => getDraft(key), [key]));
  useEffect(() => () => { if (ready) flushDraft(key); }, [key, ready]);
  const setInput = useCallback((value: SetStateAction<string>) => {
    if (ready) updateDraft(key, { text: typeof value === "function" ? value(getDraft(key).draft.text) : value });
  }, [key, ready]);
  const setContextItems = useCallback((value: SetStateAction<ContextItem[]>) => {
    if (ready) updateDraft(key, { contextItems: typeof value === "function" ? value(getDraft(key).draft.contextItems) : value });
  }, [key, ready]);
  useEffect(() => {
    if (!ready || thread !== null) return;
    try {
      const starter = localStorage.getItem("spark-starter-prompt");
      if (starter && !getDraft(key).draft.text) {
        updateDraft(key, { text: starter });
        localStorage.removeItem("spark-starter-prompt");
      }
    } catch { /* Unavailable browser storage does not prevent editing. */ }
  }, [key, ready, thread]);
  const capture = useCallback(() => {
    flushDraft(key);
    const snapshot = getDraft(key).draft.revision;
    return () => acknowledgeDraft(key, snapshot);
  }, [key]);
  return {
    input: ready ? entry.draft.text : "", contextItems: ready ? entry.draft.contextItems : [],
    setInput, setContextItems, capture, ready, isCurrent, scopeKey: key,
    status: ready ? entry.status : "checking" as const,
    discard: () => discardDraft(key),
    keepMine: () => resolveDraftConflict(key, "mine"),
    useStored: () => resolveDraftConflict(key, "stored"),
  };
}
export type ReturnTypeOfDraft = ReturnType<typeof useChatDraft>;
