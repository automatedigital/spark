/**
 * desktop.ts — bridge to the native desktop shell (Tauri, macOS app).
 *
 * Wraps the Rust commands and events added in src-tauri/src/lib.rs for the
 * menu-bar companion (§3.1), native notifications (§3.2), and spark:// deep
 * links (§3.2). Every helper no-ops cleanly when not running under Tauri, so
 * callers can invoke them unconditionally from shared components.
 */
import { isTauri } from "@/sidecar";
import type { GlobalNavTarget } from "@/lib/globalNavigation";

/** Update the tray tooltip / status to reflect agent or background activity. */
export async function setTrayStatus(busy: boolean, label?: string): Promise<void> {
  if (!isTauri()) return;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("set_tray_status", { busy, label: label ?? null });
  } catch {
    /* desktop shell unavailable — ignore */
  }
}

/** Fire a native OS notification (used when a background turn / cron completes). */
export async function nativeNotify(title: string, body: string): Promise<boolean> {
  if (!isTauri()) return false;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("notify", { title, body });
    return true;
  } catch {
    return false;
  }
}

/** Move the desktop-only agent cursor overlay to an absolute screen position. */
export async function updateAgentCursor(
  screenX: number,
  screenY: number,
  label?: string,
  active = false,
): Promise<void> {
  if (!isTauri()) return;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("agent_cursor_update", {
      screenX,
      screenY,
      label: label ?? null,
      active,
    });
  } catch {
    /* desktop shell unavailable — ignore */
  }
}

/** Hide the desktop-only agent cursor overlay. */
export async function hideAgentCursor(): Promise<void> {
  if (!isTauri()) return;
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("agent_cursor_hide");
  } catch {
    /* desktop shell unavailable — ignore */
  }
}

/** Subscribe to "start a new chat" requests from the tray / global hotkey. */
export async function onNewChat(handler: () => void): Promise<() => void> {
  if (!isTauri()) return () => {};
  try {
    const { listen } = await import("@tauri-apps/api/event");
    return await listen("spark://new-chat", () => handler());
  } catch {
    return () => {};
  }
}

/**
 * Subscribe to spark:// deep links. The payload is the raw URL string, e.g.
 * `spark://session/<id>` or `spark://canvas/<scope>/<id>`.
 */
export async function onDeepLink(handler: (url: string) => void): Promise<() => void> {
  if (!isTauri()) return () => {};
  try {
    const { listen } = await import("@tauri-apps/api/event");
    return await listen<string>("spark://open-url", (event) => handler(event.payload));
  } catch {
    return () => {};
  }
}

/**
 * Parse a spark:// deep link into a typed global-nav target (consumed by the
 * app's GLOBAL_NAV_EVENT system).
 *
 * - `spark://session/<id>`          → open chat thread
 * - `spark://canvas/<id>`           → open a global canvas
 * - `spark://canvas/<scope>/<id>`   → open a canvas in the given scope
 *                                     (`project/<slug>/<id>` carries the slug)
 *
 * Returns null when the URL isn't a recognised spark:// link.
 */
export function deepLinkToNavTarget(rawUrl: string): GlobalNavTarget | null {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return null;
  }
  if (url.protocol !== "spark:") return null;
  // For custom schemes the "host" is the first path segment.
  const segments = [url.hostname, ...url.pathname.split("/")].filter(Boolean);
  const [kind, ...rest] = segments;
  switch (kind) {
    case "session":
    case "thread":
      return rest[0] ? { type: "thread", id: rest[0] } : null;
    case "canvas":
      // canvas/<id>  ·  canvas/global/<id>  ·  canvas/project/<slug>/<id>
      if (rest[0] === "project" && rest.length >= 3) {
        return { type: "canvas", id: rest[2], scope: "project", slug: rest[1] };
      }
      if (rest[0] === "global" && rest[1]) {
        return { type: "canvas", id: rest[1], scope: "global" };
      }
      return rest[0] ? { type: "canvas", id: rest[0], scope: "global" } : null;
    default:
      return null;
  }
}
