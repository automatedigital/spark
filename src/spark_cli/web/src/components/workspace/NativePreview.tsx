import { useEffect, useRef, useState } from "react";
import { nativePreview, rectFromElement } from "@/lib/nativePreview";

/**
 * Placeholder that anchors the native child webview (desktop only). The div
 * renders nothing visible; its bounding rect drives where the real WKWebview is
 * positioned, and we keep them in sync on resize/scroll/layout changes.
 */
export function NativePreview({ slug, url, persistent = true, visible = true }: { slug: string; url: string; persistent?: boolean; visible?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const creatingRef = useRef(false);
  const createdKeyRef = useRef<string | null>(null);
  const [ready, setReady] = useState(false);

  // Create (or re-navigate) the native webview for the current URL. Toggling
  // persistence recreates the webview with a different data store.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let cancelled = false;
    setReady(false);
    const createKey = `${slug}:${url}:${persistent}`;
    createdKeyRef.current = null;
    const sync = () => {
      const rect = rectFromElement(el);
      if (cancelled || rect.width < 2 || rect.height < 2 || creatingRef.current || createdKeyRef.current === createKey) return;
      creatingRef.current = true;
      nativePreview
        .create(slug, url, rect, persistent)
        .then(async () => {
          if (cancelled) return;
          createdKeyRef.current = createKey;
          setReady(true);
          // The visibility call can race the first mount before the native
          // child exists. Repeat it after creation, matching T3's surface
          // presentation lifecycle.
          await nativePreview.setVisible(visible).catch(() => {});
        })
        .catch((e) => console.error("preview_create", e))
        .finally(() => {
          creatingRef.current = false;
        });
    };
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(el);
    const frame = requestAnimationFrame(sync);
    return () => {
      cancelled = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [slug, url, persistent, visible]);

  // The native webview overlays the panel rect, so CSS `hidden` on the React
  // pane can't conceal it — explicitly toggle visibility when the tab/panel
  // hides or shows.
  useEffect(() => {
    nativePreview.setVisible(visible).catch(() => {});
  }, [visible]);

  // Keep the native webview glued to the placeholder's rect.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const sync = () => {
      const node = ref.current;
      if (node) nativePreview.setBounds(rectFromElement(node)).catch(() => {});
    };
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    window.addEventListener("resize", sync);
    window.addEventListener("scroll", sync, true);
    // Catch layout shifts that don't fire resize/scroll (panel splits, tabs).
    const id = window.setInterval(sync, 500);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", sync);
      window.removeEventListener("scroll", sync, true);
      window.clearInterval(id);
    };
  }, []);

  // Tear down the native webview when the pane unmounts.
  useEffect(() => {
    return () => {
      nativePreview.destroy().catch(() => {});
    };
  }, []);

  return (
    <div ref={ref} className="relative h-full w-full bg-white">
      {!ready && (
        <div className="absolute inset-0 z-0 flex items-center justify-center bg-[#101112] text-[11px] text-white/45">
          Loading preview…
        </div>
      )}
    </div>
  );
}
