import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Download } from "lucide-react";
import { api } from "@/lib/api";
import type { StreamBrowserInput } from "@/lib/api";
import { mapToViewport } from "@/lib/browserCoords";

const FRAME_INTERVAL_MS = 500;

// Map a DOM KeyboardEvent into agent-browser's `press` combo syntax
// (e.g. "Control+c", "Meta+a", "Shift+Tab") for keyboard-shortcut parity.
function toComboKey(e: React.KeyboardEvent): string {
  const mods: string[] = [];
  if (e.ctrlKey) mods.push("Control");
  if (e.altKey) mods.push("Alt");
  if (e.shiftKey) mods.push("Shift");
  if (e.metaKey) mods.push("Meta");
  const key = e.key === " " ? "Space" : e.key;
  return [...mods, key].join("+");
}

export function StreamedBrowser({
  slug,
  url,
  persistent = true,
  onTitle,
}: {
  slug: string;
  url: string;
  persistent?: boolean;
  onTitle?: (title: string) => void;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const [frameSrc, setFrameSrc] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // When the backend (agent-browser/Chromium or Playwright) isn't installed,
  // we surface a friendly install state instead of a broken <img>.
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [installing, setInstalling] = useState(false);
  // True once the CDP screencast SSE is pushing frames; while active we stop
  // polling /frame entirely. On 501/error we fall back to the polled source.
  const [screencast, setScreencast] = useState(false);
  const objectUrlRef = useRef<string | null>(null);

  const refetchFrame = useCallback(() => {
    if (unavailable || screencast) return;
    setFrameSrc(api.streamBrowserFrameUrl(slug, Date.now()));
  }, [slug, unavailable, screencast]);

  // Start the session at the target URL, then begin polling frames.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setUnavailable(null);
    setScreencast(false);
    setFrameSrc("");
    api
      .streamBrowserNavigate(slug, url, persistent)
      .then((res) => {
        if (cancelled) return;
        if (res?.title) onTitle?.(res.title);
        refetchFrame();
      })
      .catch((e) => {
        if (cancelled) return;
        // 501 => backend missing: show the install/error state, hide the frame.
        const status = (e as { status?: number })?.status;
        const message = String((e as { message?: string })?.message ?? e);
        if (status === 501) {
          setUnavailable(message);
        } else {
          setError(message);
        }
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [slug, url, persistent, onTitle, refetchFrame]);

  // Preferred frame source: CDP screencast over SSE (push). Each base64 JPEG
  // frame is turned into a blob URL and shown in the <img>. If the stream
  // fails to open (501/network) we silently leave `screencast` false and the
  // polling effect below takes over — the v1 graceful fallback.
  useEffect(() => {
    if (unavailable) return;
    let closed = false;
    const es = new EventSource(api.streamBrowserScreencastUrl(slug));
    es.onmessage = (ev) => {
      if (closed) return;
      try {
        const data = JSON.parse(ev.data) as { frame?: string };
        if (!data.frame) return;
        const bytes = Uint8Array.from(atob(data.frame), (c) => c.charCodeAt(0));
        const blob = new Blob([bytes], { type: "image/jpeg" });
        const next = URL.createObjectURL(blob);
        if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = next;
        setScreencast(true);
        setFrameSrc(next);
        setLoading(false);
      } catch {
        /* ignore malformed frame */
      }
    };
    es.onerror = () => {
      // 501 (unsupported) or a dropped connection → fall back to polling.
      es.close();
      if (!closed) setScreencast(false);
    };
    return () => {
      closed = true;
      es.close();
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, [slug, url, unavailable]);

  // Poll for fresh frames — only while the screencast isn't active (fallback).
  useEffect(() => {
    if (unavailable || screencast) return;
    const id = window.setInterval(refetchFrame, FRAME_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refetchFrame, unavailable, screencast]);

  const sendInput = useCallback(
    (input: StreamBrowserInput) => {
      void api
        .streamBrowserInput(slug, input)
        // Only nudge a polled refetch; the screencast pushes its own frames.
        .then(() => refetchFrame())
        .catch((e) => {
          const status = (e as { status?: number })?.status;
          const message = String((e as { message?: string })?.message ?? e);
          if (status === 501) setUnavailable(message);
          // 400 = input unsupported by the active backend; ignore quietly.
          else if (status !== 400) setError(message);
        });
    },
    [slug, refetchFrame],
  );

  const pointFromEvent = useCallback((clientX: number, clientY: number) => {
    const img = imgRef.current;
    if (!img) return null;
    return mapToViewport(clientX, clientY, img.getBoundingClientRect());
  }, []);

  const onInstall = useCallback(() => {
    setInstalling(true);
    setError(null);
    api
      .installStreamBrowser(slug)
      .then((res) => {
        if (res?.ok) {
          // Re-trigger the navigate effect by clearing the unavailable state.
          setUnavailable(null);
          setLoading(true);
          api
            .streamBrowserNavigate(slug, url, persistent)
            .then((r) => {
              if (r?.title) onTitle?.(r.title);
              refetchFrame();
            })
            .catch((e) => setUnavailable(String((e as { message?: string })?.message ?? e)))
            .finally(() => setLoading(false));
        } else {
          setUnavailable(res?.error || "Install failed");
        }
      })
      .catch((e) => setUnavailable(String((e as { message?: string })?.message ?? e)))
      .finally(() => setInstalling(false));
  }, [slug, url, persistent, onTitle, refetchFrame]);

  // ── Install / unavailable state ──
  if (unavailable) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-3 bg-black/40 px-6 text-center">
        <div className="max-w-sm text-sm text-muted-foreground">
          The preview browser isn’t set up yet.
        </div>
        <div className="max-w-sm font-mono-ui text-[11px] text-muted-foreground/70">
          {unavailable}
        </div>
        <button
          type="button"
          onClick={onInstall}
          disabled={installing}
          className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium hover:bg-accent disabled:opacity-60"
        >
          {installing ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Download className="h-3.5 w-3.5" />
          )}
          {installing ? "Installing…" : "Install browser runtime"}
        </button>
        <div className="max-w-sm text-[10px] text-muted-foreground/60">
          You can also run <code>spark doctor</code> in a terminal to set this up.
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex h-full w-full items-center justify-center bg-black/40">
      {frameSrc ? (
        <img
          ref={imgRef}
          src={frameSrc}
          alt="Streamed browser"
          tabIndex={0}
          onClick={(e) => {
            const point = pointFromEvent(e.clientX, e.clientY);
            if (point) sendInput({ type: "click", x: point.x, y: point.y });
          }}
          onContextMenu={(e) => {
            e.preventDefault();
            const point = pointFromEvent(e.clientX, e.clientY);
            if (point) sendInput({ type: "rightclick", x: point.x, y: point.y });
          }}
          onWheel={(e) => sendInput({ type: "scroll", dx: e.deltaX, dy: e.deltaY })}
          onKeyDown={(e) => {
            // Plain printable char → type it; everything else (incl. modifier
            // combos like Ctrl/Cmd+C) → forward as a `press` combo for parity.
            if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
              sendInput({ type: "type", text: e.key });
            } else {
              sendInput({ type: "key", key: toComboKey(e) });
            }
            e.preventDefault();
          }}
          className="h-full w-full object-contain outline-none"
          draggable={false}
        />
      ) : null}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/30 text-xs text-muted-foreground/80">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Starting browser…
        </div>
      )}
      {error && (
        <div className="absolute bottom-2 left-2 right-2 rounded-sm border border-red-500/40 bg-red-950/60 px-2 py-1 font-mono-ui text-[10px] text-red-200">
          {error}
        </div>
      )}
    </div>
  );
}
