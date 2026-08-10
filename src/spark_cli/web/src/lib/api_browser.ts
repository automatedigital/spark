/** browser endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  StreamBrowserConsoleEntry,
  StreamBrowserDownload,
  StreamBrowserInput,
  StreamBrowserPickedElement,
  StreamBrowserTab,
} from "./apiTypes";

export const browserApi = {
  streamBrowserNavigate: (slug: string, url: string, persistent = true) =>
    fetchJSON<{ slug: string; url: string; title: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/navigate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, persistent }),
      },
    ),

  /** Relative URL for the latest frame; pass a cache-buster to force a refetch. */
  streamBrowserFrameUrl: (slug: string, bust: number) =>
    `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/frame?t=${bust}`,

  /** SSE endpoint that pushes CDP-screencast JPEG frames (base64). 501 → poll. */
  streamBrowserScreencastUrl: (slug: string) =>
    `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/screencast`,
  streamBrowserInput: (slug: string, input: StreamBrowserInput) =>
    fetchJSON<{ slug: string; ok: boolean; url: string; title: string; clipboard?: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/input`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input),
      },
    ),
  streamBrowserBackend: (slug: string) =>
    fetchJSON<{ slug: string; backend: string; available: boolean; detail: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/backend`,
    ),

  /** Resize the streamed viewport (responsive presets). */
  streamBrowserViewport: (slug: string, width: number, height: number) =>
    fetchJSON<{ slug: string; width: number; height: number }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/viewport`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ width, height }),
      },
    ),

  /** Toggle dark-mode (prefers-color-scheme) emulation; dark=null clears. */
  streamBrowserEmulate: (slug: string, dark: boolean | null) =>
    fetchJSON<{ slug: string; dark: boolean | null }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/emulate`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dark }),
      },
    ),
  streamBrowserTabs: (slug: string) =>
    fetchJSON<{ slug: string; tabs: StreamBrowserTab[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/tabs`,
    ),
  streamBrowserTabAction: (
    slug: string,
    action: "new" | "switch" | "close",
    opts?: { url?: string; target_id?: string },
  ) =>
    fetchJSON<{ slug: string; ok: boolean; url?: string; title?: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/tabs`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ...opts }),
      },
    ),
  streamBrowserDownloads: (slug: string) =>
    fetchJSON<{ slug: string; downloads: StreamBrowserDownload[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/downloads`,
    ),

  /** Whether the user currently holds control (take-over) of the session. */
  streamBrowserTakeoverState: (slug: string) =>
    fetchJSON<{ slug: string; paused: boolean; ts: number }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/takeover`,
    ),

  /** Grab (true) or release (false) control of the shared session. */
  streamBrowserTakeover: (slug: string, paused: boolean) =>
    fetchJSON<{ slug: string; paused: boolean }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/takeover`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paused }),
      },
    ),

  /** Element picker: describe the element at a pane coordinate. */
  streamBrowserPick: (slug: string, x: number, y: number) =>
    fetchJSON<{ slug: string; element: StreamBrowserPickedElement }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/pick`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x, y }),
      },
    ),

  /** Capture the current frame as PNG (saved to workspace) for send-to-chat. */
  streamBrowserScreenshot: (slug: string) =>
    fetchJSON<{ slug: string; url: string; png_base64: string; name: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/screenshot`,
    ),

  /** Record a short flow as an animated GIF saved to the workspace. */
  streamBrowserRecord: (slug: string, frames = 12, interval = 0.4) =>
    fetchJSON<{ slug: string; name: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/record`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ frames, interval }),
      },
    ),

  /** Captured console/network/exception entries from the previewed page. */
  streamBrowserConsole: (slug: string, sinceSeq = 0) =>
    fetchJSON<{ slug: string; entries: StreamBrowserConsoleEntry[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/console?since_seq=${sinceSeq}`,
    ),

  /** Auto-detected local dev servers owned by this workspace. */
  installStreamBrowser: (slug: string) =>
    fetchJSON<{ slug: string; ok: boolean; error?: string | null; version?: string }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/install`,
      { method: "POST" },
    ),
  stopStreamBrowser: (slug: string) =>
    fetchJSON<{ slug: string; stopped: boolean }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/stop`,
      { method: "POST" },
    ),
  streamBrowserCookies: (slug: string) =>
    fetchJSON<{ slug: string; cookies: { name: string; domain: string }[] }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/cookies`,
    ),
  clearStreamBrowser: (slug: string) =>
    fetchJSON<{ slug: string; cleared: boolean }>(
      `/api/workspace/projects/${encodeURIComponent(slug)}/preview/stream/clear`,
      { method: "POST" },
    ),
};
