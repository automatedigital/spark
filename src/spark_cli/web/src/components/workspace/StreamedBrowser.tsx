import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
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

  const refetchFrame = useCallback(() => {
    setFrameSrc(api.streamBrowserFrameUrl(slug, Date.now()));
  }, [slug]);

  // Start the session at the target URL, then begin polling frames.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .streamBrowserNavigate(slug, url, persistent)
      .then((res) => {
        if (cancelled) return;
        if (res?.title) onTitle?.(res.title);
        refetchFrame();
      })
      .catch((e) => !cancelled && setError(String(e?.message ?? e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [slug, url, persistent, onTitle, refetchFrame]);

  // Poll for fresh frames.
  useEffect(() => {
    const id = window.setInterval(refetchFrame, FRAME_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refetchFrame]);

  const sendInput = useCallback(
    (input: StreamBrowserInput) => {
      void api
        .streamBrowserInput(slug, input)
        .then(() => refetchFrame())
        .catch((e) => setError(String(e?.message ?? e)));
    },
    [slug, refetchFrame],
  );

  const onClick = (e: React.MouseEvent<HTMLImageElement>) => {
    const img = imgRef.current;
    if (!img) return;
    const point = mapToViewport(e.clientX, e.clientY, img.getBoundingClientRect());
    if (point) sendInput({ type: "click", x: point.x, y: point.y });
  };

  const onWheel = (e: React.WheelEvent<HTMLImageElement>) => {
    sendInput({ type: "scroll", dx: e.deltaX, dy: e.deltaY });
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLImageElement>) => {
    // Single printable chars go through type; named keys through press.
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      sendInput({ type: "type", text: e.key });
    } else {
      sendInput({ type: "key", key: e.key });
    }
    e.preventDefault();
  };

  return (
    <div className="relative flex h-full w-full items-center justify-center bg-black/40">
      {frameSrc ? (
        <img
          ref={imgRef}
          src={frameSrc}
          alt="Streamed browser"
          tabIndex={0}
          onClick={onClick}
          onWheel={onWheel}
          onKeyDown={onKeyDown}
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
