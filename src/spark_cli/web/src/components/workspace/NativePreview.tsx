import { useEffect, useRef } from "react";
import { nativePreview, rectFromElement } from "@/lib/nativePreview";

/**
 * Placeholder that anchors the native child webview (desktop only). The div
 * renders nothing visible; its bounding rect drives where the real WKWebview is
 * positioned, and we keep them in sync on resize/scroll/layout changes.
 */
export function NativePreview({ slug, url, persistent = true }: { slug: string; url: string; persistent?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  // Create (or re-navigate) the native webview for the current URL. Toggling
  // persistence recreates the webview with a different data store.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    nativePreview.destroy().catch(() => {});
    nativePreview
      .create(slug, url, rectFromElement(el), persistent)
      .catch((e) => console.error("preview_create", e));
  }, [slug, url, persistent]);

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

  return <div ref={ref} className="h-full w-full" />;
}
