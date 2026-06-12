import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, Download } from "lucide-react";
import { api } from "@/lib/api";
import type { StreamBrowserInput } from "@/lib/api";
import { mapToViewport } from "@/lib/browserCoords";

const FRAME_INTERVAL_MS = 500;

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

  const refetchFrame = useCallback(() => {
    if (unavailable) return;
    setFrameSrc(api.streamBrowserFrameUrl(slug, Date.now()));
  }, [slug, unavailable]);

  // Start the session at the target URL, then begin polling frames.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setUnavailable(null);
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

  // Poll for fresh frames (paused while the backend is unavailable).
  useEffect(() => {
    if (unavailable) return;
    const id = window.setInterval(refetchFrame, FRAME_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refetchFrame, unavailable]);

  const sendInput = useCallback(
    (input: StreamBrowserInput) => {
      void api
        .streamBrowserInput(slug, input)
        .then(() => refetchFrame())
        .catch((e) => {
          const status = (e as { status?: number })?.status;
          const message = String((e as { message?: string })?.message ?? e);
          if (status === 501) setUnavailable(message);
          else setError(message);
        });
    },
    [slug, refetchFrame],
  );

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
            const img = imgRef.current;
            if (!img) return;
            const point = mapToViewport(e.clientX, e.clientY, img.getBoundingClientRect());
            if (point) sendInput({ type: "click", x: point.x, y: point.y });
          }}
          onWheel={(e) => sendInput({ type: "scroll", dx: e.deltaX, dy: e.deltaY })}
          onKeyDown={(e) => {
            if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
              sendInput({ type: "type", text: e.key });
            } else {
              sendInput({ type: "key", key: e.key });
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
