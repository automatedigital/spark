import { useCallback, useEffect, useRef, useState } from "react";
import { GLOBAL_NAV_EVENT, takeMessageAnchor, type GlobalNavTarget } from "@/lib/globalNavigation";
import { readMessageWindow, type MessageWindow } from "@/lib/messageAnchorClient";
import { paletteScope } from "@/lib/paletteClient";
import { isAbortError } from "@/lib/readOwner";

// This read-only viewport never writes the controller transcript or live reducer.
export function useMessageAnchor(sessionId: string | null, isCurrent: () => boolean) {
  const [window, setWindow] = useState<MessageWindow | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const anchor = useRef<string | null>(null);
  const scope = useRef(paletteScope());
  const close = useCallback(() => {
    request.current?.abort();
    anchor.current = null;
    setWindow(null);
    setError(null);
    setLoading(false);
  }, []);
  const load = useCallback(async (id: string, direction?: { before_id: number } | { after_id: number }) => {
    if (!sessionId || !isCurrent()) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    scope.current = paletteScope();
    anchor.current = id;
    setLoading(true);
    setError(null);
    try {
      const result = await readMessageWindow(sessionId, id, controller.signal, direction);
      if (!controller.signal.aborted && isCurrent() && scope.current === paletteScope()) setWindow(result);
    } catch (err) {
      if (!isAbortError(err) && !controller.signal.aborted && isCurrent() && scope.current === paletteScope()) {
        setError("Unable to open this message. Return to latest or reopen the search result.");
      }
    } finally {
      if (request.current === controller && !controller.signal.aborted && isCurrent()) setLoading(false);
    }
  }, [isCurrent, sessionId]);
  useEffect(() => {
    const open = (event?: Event) => {
      const target = (event as CustomEvent<GlobalNavTarget> | undefined)?.detail;
      if (target?.type === "thread" && target.id === sessionId && !target.messageId) { close(); return; }
      const id = sessionId ? takeMessageAnchor(sessionId) : null;
      if (id) void load(id);
    };
    open();
    globalThis.window.addEventListener(GLOBAL_NAV_EVENT, open);
    return () => { globalThis.window.removeEventListener(GLOBAL_NAV_EVENT, open); request.current?.abort(); };
  }, [close, load, sessionId]);
  const page = useCallback((direction: "older" | "newer") => {
    if (!window || !anchor.current || loading) return;
    const cursor = direction === "older" ? window.before_id : window.after_id;
    if (cursor != null) void load(anchor.current, direction === "older" ? { before_id: cursor } : { after_id: cursor });
  }, [load, loading, window]);
  return { window: scope.current === paletteScope() ? window : null, loading, error, close, page };
}
