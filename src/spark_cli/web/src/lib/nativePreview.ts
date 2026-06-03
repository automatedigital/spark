/**
 * nativePreview.ts — bridge to the native child webview (desktop only).
 *
 * In the macOS app the preview pane is a real WKWebView overlaid on the React
 * panel's DOM rect (see src-tauri/src/lib.rs). It renders external sites that an
 * iframe can't (no X-Frame-Options/CSP framing limits) and keeps a persistent
 * cookie store. These helpers invoke the Rust commands; they no-op cleanly when
 * not running under Tauri.
 */
import { invoke } from "@tauri-apps/api/core";
import { isTauri } from "@/sidecar";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** getBoundingClientRect is viewport-relative CSS px, which matches the Tauri
 * window content area (the webview fills the window), so it maps 1:1 to the
 * native webview's LogicalPosition/LogicalSize. */
export function rectFromElement(el: HTMLElement): Rect {
  const r = el.getBoundingClientRect();
  return { x: Math.round(r.left), y: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) };
}

export const nativePreview = {
  available: () => isTauri(),

  create: (slug: string, url: string, rect: Rect, persistent = true) =>
    invoke("preview_create", {
      slug,
      url,
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
      persistent,
    }),

  setBounds: (rect: Rect) =>
    invoke("preview_set_bounds", { x: rect.x, y: rect.y, width: rect.width, height: rect.height }),

  navigate: (url: string) => invoke("preview_navigate", { url }),

  setVisible: (visible: boolean) => invoke("preview_set_visible", { visible }),

  back: () => invoke("preview_back"),

  forward: () => invoke("preview_forward"),

  cookies: () => invoke<{ name: string; domain: string }[]>("preview_cookies"),

  clearData: () => invoke("preview_clear_data"),

  devtools: () => invoke("preview_devtools"),

  destroy: () => invoke("preview_destroy"),
};
