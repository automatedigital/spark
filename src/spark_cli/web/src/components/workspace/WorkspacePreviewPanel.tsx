import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  Cookie,
  EyeOff,
  ExternalLink,
  Globe,
  Lock,
  Camera,
  Hand,
  Loader2,
  Maximize2,
  Minimize2,
  Monitor,
  Moon,
  MoreHorizontal,
  MousePointerClick,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  ScrollText,
  Smartphone,
  Square,
  Tablet,
  Terminal,
  Trash2,
  Video,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  StreamBrowserTab,
  WorkspacePreviewEvent,
  WorkspacePreviewLog,
  WorkspacePreviewStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { previewAutoOpenEnabled, setPreviewAutoOpen } from "@/lib/previewPrefs";
import { isTauri } from "@/sidecar";
import { StreamedBrowser } from "./StreamedBrowser";
import { NativePreview } from "./NativePreview";
import { nativePreview } from "@/lib/nativePreview";
import { isDirectPreviewUrl } from "@/lib/previewUrl";

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

/** Favicon served from the site's own origin (no third-party request). */
function faviconUrl(url: string): string {
  try {
    return `${new URL(url).origin}/favicon.ico`;
  } catch {
    return "";
  }
}

function statusDot(status: WorkspacePreviewStatus["status"]): string {
  if (status === "running") return "bg-emerald-400";
  if (status === "starting") return "bg-amber-400";
  if (status === "failed") return "bg-red-400";
  return "bg-muted-foreground/50";
}

function shortTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Device viewport presets — constrain the preview region; centered. The native
// webview tracks its placeholder's rect, so the same wrapper works on desktop.
type DeviceId = "responsive" | "phone" | "tablet" | "desktop";
const DEVICES: { id: DeviceId; label: string; width: number | null; Icon: typeof Monitor }[] = [
  { id: "responsive", label: "Responsive", width: null, Icon: Monitor },
  { id: "phone", label: "iPhone", width: 390, Icon: Smartphone },
  { id: "tablet", label: "iPad", width: 820, Icon: Tablet },
  { id: "desktop", label: "Desktop", width: 1280, Icon: Monitor },
];

export function WorkspacePreviewPanel({ slug, visible = true }: { slug: string; visible?: boolean }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const urlInputRef = useRef<HTMLInputElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<WorkspacePreviewStatus | null>(null);
  const [frameSrc, setFrameSrc] = useState("");
  const [urlInput, setUrlInput] = useState("");
  const [logs, setLogs] = useState<WorkspacePreviewLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [logFilter, setLogFilter] = useState<"all" | "server" | "console" | "network" | "error">("all");
  const [lastRefreshReason, setLastRefreshReason] = useState<string | null>(null);
  const [portOverride, setPortOverride] = useState("");
  const [privateMode, setPrivateMode] = useState(false);
  const [pageTitle, setPageTitle] = useState("");
  const [showMenu, setShowMenu] = useState(false);
  const [device, setDevice] = useState<DeviceId>("responsive");
  const [autoOpen, setAutoOpen] = useState(previewAutoOpenEnabled);
  const [darkEmulation, setDarkEmulation] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [tabs, setTabs] = useState<StreamBrowserTab[]>([]);
  const [takeover, setTakeover] = useState(false);
  const [picking, setPicking] = useState(false);
  const [recording, setRecording] = useState(false);
  const [showActionLog, setShowActionLog] = useState(false);
  const [actions, setActions] = useState<import("@/lib/api").BrowserActionLogEntry[]>([]);
  // Follow-agent overlay: most recent agent action (from the audit log).
  const [agentAction, setAgentAction] = useState<{ action: string; ref?: string; ts: number } | null>(null);
  const agentActionTsRef = useRef(0);
  const [dialog, setDialog] = useState<{
    title: string;
    body?: React.ReactNode;
    confirmLabel?: string;
    destructive?: boolean;
    onConfirm?: () => void;
  } | null>(null);

  const activeUrl = status?.url ?? "";
  const previewPending = status?.status === "starting";
  const deviceWidth = DEVICES.find((d) => d.id === device)?.width ?? null;
  // Streamed (server-side browser) mode: external origin, not native/iframe.
  const streamedMode = !isTauri() && !!frameSrc && !isDirectPreviewUrl(frameSrc);

  // Push the selected device preset to the streamed backend so the server-side
  // viewport (and click-coordinate mapping) matches what the pane renders.
  useEffect(() => {
    if (!streamedMode) return;
    const w = deviceWidth ?? 1280;
    const h = device === "phone" ? 844 : device === "tablet" ? 1180 : 800;
    void api.streamBrowserViewport(slug, w, h).catch(() => {});
  }, [streamedMode, deviceWidth, device, slug]);

  const toggleDarkEmulation = useCallback(() => {
    const next = !darkEmulation;
    setDarkEmulation(next);
    setShowMenu(false);
    void api.streamBrowserEmulate(slug, next ? true : null).catch(() => {});
  }, [darkEmulation, slug]);

  const refreshTabs = useCallback(() => {
    if (!streamedMode) {
      setTabs([]);
      return;
    }
    void api
      .streamBrowserTabs(slug)
      .then((r) => setTabs(r.tabs ?? []))
      .catch(() => setTabs([]));
  }, [streamedMode, slug]);

  useEffect(() => {
    refreshTabs();
  }, [refreshTabs, frameSrc]);

  const openTab = useCallback(() => {
    void api
      .streamBrowserTabAction(slug, "new", { url: "about:blank" })
      .then(() => refreshTabs())
      .catch(() => {});
  }, [slug, refreshTabs]);

  const switchTab = useCallback(
    (id: string) => {
      void api
        .streamBrowserTabAction(slug, "switch", { target_id: id })
        .then(() => refreshTabs())
        .catch(() => {});
    },
    [slug, refreshTabs],
  );

  const closeTab = useCallback(
    (id: string) => {
      void api
        .streamBrowserTabAction(slug, "close", { target_id: id })
        .then(() => refreshTabs())
        .catch(() => {});
    },
    [slug, refreshTabs],
  );

  // ── Agent ⇄ user collaboration ──
  const toggleTakeover = useCallback(() => {
    const next = !takeover;
    setTakeover(next);
    void api.streamBrowserTakeover(slug, next).catch(() => setTakeover(!next));
  }, [takeover, slug]);

  // Poll take-over state so the badge reflects external toggles.
  useEffect(() => {
    if (!streamedMode) return;
    let alive = true;
    const tick = () =>
      void api
        .streamBrowserTakeoverState(slug)
        .then((r) => alive && setTakeover(r.paused))
        .catch(() => {});
    tick();
    const id = window.setInterval(tick, 3000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [streamedMode, slug]);

  // Follow-agent overlay: surface the agent's most recent browser action.
  useEffect(() => {
    if (!streamedMode) return;
    let alive = true;
    const tick = () =>
      void api
        .getWorkspacePreviewActionLog(slug, agentActionTsRef.current, 20)
        .then((r) => {
          if (!alive || !r.actions.length) return;
          const last = r.actions[r.actions.length - 1];
          agentActionTsRef.current = last.ts;
          const ref = (last.detail?.ref as string | undefined) ?? undefined;
          setAgentAction({ action: last.action, ref, ts: Date.now() });
        })
        .catch(() => {});
    tick();
    const id = window.setInterval(tick, 1500);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [streamedMode, slug]);

  // Auto-fade the follow-agent toast a few seconds after the last action.
  useEffect(() => {
    if (!agentAction) return;
    const id = window.setTimeout(() => setAgentAction(null), 4000);
    return () => window.clearTimeout(id);
  }, [agentAction]);

  // Dev-loop: poll captured console/network errors from the previewed page and
  // surface them in the console drawer (closes the edit→reload→check loop).
  const consoleSeqRef = useRef(0);
  useEffect(() => {
    if (!streamedMode) return;
    consoleSeqRef.current = 0;
    let alive = true;
    const tick = () =>
      void api
        .streamBrowserConsole(slug, consoleSeqRef.current)
        .then((r) => {
          if (!alive || !r.entries.length) return;
          consoleSeqRef.current = r.entries[r.entries.length - 1].seq;
          setLogs((prev) => [
            ...prev.slice(-499),
            ...r.entries.map((e) => ({
              ts: e.ts,
              type: "log" as const,
              stream: e.kind === "network" ? "network" : e.level === "error" || e.kind === "exception" ? "error" : "console",
              text: e.text,
            })),
          ]);
        })
        .catch(() => {});
    tick();
    const id = window.setInterval(tick, 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [streamedMode, slug, frameSrc]);

  // Action-log pane: poll the auditable agent action transcript while open.
  useEffect(() => {
    if (!showActionLog) return;
    let alive = true;
    const tick = () =>
      void api
        .getWorkspacePreviewActionLog(slug)
        .then((r) => alive && setActions(r.actions))
        .catch(() => {});
    tick();
    const id = window.setInterval(tick, 2000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [showActionLog, slug]);

  // Dev-loop: auto-detect running local dev servers to offer in the URL bar.
  const [devServers, setDevServers] = useState<{ url: string; port: number }[]>([]);
  useEffect(() => {
    let alive = true;
    const tick = () =>
      void api
        .detectDevServers(slug)
        .then((r) => alive && setDevServers(r.servers ?? []))
        .catch(() => {});
    tick();
    const id = window.setInterval(tick, 8000);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [slug]);

  const screenshotToChat = useCallback(() => {
    setShowMenu(false);
    void api
      .streamBrowserScreenshot(slug)
      .then((r) => {
        const ref = r.name ? `downloads/${r.name}` : "the current preview screenshot";
        window.dispatchEvent(
          new CustomEvent("spark:compose", {
            detail: `Here's a screenshot of the preview (${r.url}). See \`${ref}\`. `,
          }),
        );
      })
      .catch(() => {});
  }, [slug]);

  const recordFlow = useCallback(() => {
    setShowMenu(false);
    setRecording(true);
    void api
      .streamBrowserRecord(slug)
      .then((r) => {
        window.dispatchEvent(
          new CustomEvent("spark:compose", {
            detail: `Recorded a short flow of the preview for a bug report: \`downloads/${r.name}\`. `,
          }),
        );
        refreshTabs();
      })
      .catch(() => {})
      .finally(() => setRecording(false));
  }, [slug, refreshTabs]);

  const onPickElement = useCallback(
    (x: number, y: number) => {
      void api
        .streamBrowserPick(slug, x, y)
        .then((r) => {
          const el = r.element ?? {};
          const label = el.text || el.name || el.selector || el.tag || "element";
          const detail =
            `Fix this element in the preview: **${label}**` +
            (el.selector ? `\n- selector: \`${el.selector}\`` : "") +
            (el.role ? `\n- role: ${el.role}` : "") +
            (el.url ? `\n- page: ${el.url}` : "");
          window.dispatchEvent(new CustomEvent("spark:compose", { detail }));
        })
        .catch(() => {})
        .finally(() => setPicking(false));
    },
    [slug],
  );

  useEffect(() => {
    // An iframe keeps an already-loaded JavaScript app alive even after its
    // backing dev server has stopped. Remove the browsing context when the
    // backend says the preview is no longer running so the panel cannot look
    // active while the toolbar correctly shows Start.
    setFrameSrc(status?.status === "running" ? activeUrl : "");
    setPageTitle("");
  }, [activeUrl, status?.status]);

  useEffect(() => {
    if (!showMenu) return;
    const onDocClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setShowMenu(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [showMenu]);

  const reloadFrame = useCallback(() => {
    if (isTauri()) {
      if (activeUrl) void nativePreview.navigate(activeUrl).catch(() => {});
      return;
    }
    const frame = iframeRef.current;
    if (!frame) return;
    try {
      frame.contentWindow?.location.reload();
    } catch {
      setFrameSrc("");
      window.setTimeout(() => setFrameSrc(activeUrl), 0);
    }
  }, [activeUrl]);

  const loadStatus = useCallback(async () => {
    try {
      const next = await api.getWorkspacePreviewStatus(slug);
      setStatus(next);
      setUrlInput(next.url ?? "");
    } catch (e) {
      console.error("Browser status failed", e);
    }
  }, [slug]);

  const loadLogs = useCallback(async () => {
    try {
      const res = await api.getWorkspacePreviewLogs(slug);
      setLogs(res.logs);
    } catch (e) {
      console.error("Browser logs failed", e);
    }
  }, [slug]);

  useEffect(() => {
    void loadStatus();
    void loadLogs();
    const source = api.streamWorkspacePreviewEvents(slug);
    eventSourceRef.current = source;
    source.onmessage = (ev) => {
      const event = JSON.parse(ev.data) as WorkspacePreviewEvent;
      if (event.type === "state") {
        setStatus(event);
        setUrlInput(event.url ?? "");
      } else if (event.type === "log") {
        setLogs((prev) => [...prev.slice(-499), event]);
      } else if (event.type === "refresh") {
        setLastRefreshReason(event.reason ?? "manual");
        reloadFrame();
      }
    };
    source.onerror = () => {
      source.close();
      if (eventSourceRef.current === source) eventSourceRef.current = null;
    };
    return () => {
      source.close();
      if (eventSourceRef.current === source) eventSourceRef.current = null;
    };
  }, [loadLogs, loadStatus, reloadFrame, slug]);

  const parsedPort = () => {
    const n = Number.parseInt(portOverride.trim(), 10);
    return Number.isInteger(n) && n >= 1 && n <= 65535 ? n : undefined;
  };

  const start = async () => {
    setLoading(true);
    try {
      const next = await api.startWorkspacePreview(slug, { port: parsedPort() });
      setStatus(next);
      setUrlInput(next.url ?? "");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const openFromChat = () => {
      // Chat responses can contain a port from an earlier preview run. Start
      // (or reuse) the project instead of navigating to that potentially stale
      // address; the returned status supplies the live URL to this panel.
      setLoading(true);
      void api
        .startWorkspacePreview(slug, {})
        .then((next) => {
          setStatus(next);
          setUrlInput(next.url ?? "");
        })
        .finally(() => setLoading(false));
    };
    window.addEventListener("spark:preview-open", openFromChat);
    return () => window.removeEventListener("spark:preview-open", openFromChat);
  }, [slug]);

  const stop = async () => {
    setLoading(true);
    try {
      const next = await api.stopWorkspacePreview(slug);
      setStatus(next);
      setFrameSrc("");
      setPageTitle("");
    } finally {
      setLoading(false);
    }
  };

  const restart = async () => {
    setLoading(true);
    try {
      const next = await api.restartWorkspacePreview(slug, { port: parsedPort() });
      setStatus(next);
      setUrlInput(next.url ?? "");
    } finally {
      setLoading(false);
    }
  };

  const goBack = () => {
    if (isTauri()) return void nativePreview.back().catch(() => {});
    if (frameSrc && !isDirectPreviewUrl(frameSrc)) return void api.streamBrowserInput(slug, { type: "back" }).catch(() => {});
    try {
      iframeRef.current?.contentWindow?.history.back();
    } catch {
      /* cross-origin */
    }
  };

  const goForward = () => {
    if (isTauri()) return void nativePreview.forward().catch(() => {});
    if (frameSrc && !isDirectPreviewUrl(frameSrc)) return void api.streamBrowserInput(slug, { type: "forward" }).catch(() => {});
    try {
      iframeRef.current?.contentWindow?.history.forward();
    } catch {
      /* cross-origin */
    }
  };

  const performNavigate = async (target: string) => {
    setLoading(true);
    try {
      const next = await api.navigateWorkspacePreview(slug, target);
      setStatus(next);
    } finally {
      setLoading(false);
    }
  };

  const navigate = () => {
    const trimmed = urlInput.trim();
    if (!trimmed) return;
    // Guard against silently driving the browser to an arbitrary external
    // origin: confirm before navigating anywhere that isn't local loopback.
    const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
    if (!isDirectPreviewUrl(withScheme)) {
      let host = withScheme;
      try {
        host = new URL(withScheme).host;
      } catch {
        /* keep raw */
      }
      setDialog({
        title: "Navigate to external site?",
        body: <span>The preview browser will load <span className="font-mono-ui text-foreground">{host}</span>.</span>,
        confirmLabel: "Navigate",
        onConfirm: () => void performNavigate(trimmed),
      });
      return;
    }
    void performNavigate(trimmed);
  };

  const refresh = () => {
    setLastRefreshReason("manual");
    reloadFrame();
    void api.refreshWorkspacePreview(slug).catch(() => {});
  };

  const clearBrowsingData = () => {
    setShowMenu(false);
    setDialog({
      title: "Clear browsing data?",
      body: "Signs out of all sites and clears cookies for this workspace.",
      confirmLabel: "Clear",
      destructive: true,
      onConfirm: () => {
        void (async () => {
          try {
            if (isTauri()) await nativePreview.clearData();
            else await api.clearStreamBrowser(slug);
          } catch (e) {
            console.error("clear browsing data", e);
          }
        })();
      },
    });
  };

  const showCookies = async () => {
    setShowMenu(false);
    try {
      const cookies = isTauri()
        ? await nativePreview.cookies()
        : (await api.streamBrowserCookies(slug)).cookies;
      const byDomain = new Map<string, number>();
      for (const c of cookies) byDomain.set(c.domain, (byDomain.get(c.domain) ?? 0) + 1);
      const rows = [...byDomain.entries()];
      setDialog({
        title: cookies.length ? `Cookies (${cookies.length})` : "Cookies",
        body: rows.length ? (
          <div className="flex flex-col gap-0.5 font-mono-ui text-[11px]">
            {rows.map(([d, n]) => (
              <div key={d} className="flex justify-between gap-3"><span className="truncate">{d}</span><span className="text-muted-foreground/60">{n}</span></div>
            ))}
          </div>
        ) : "No cookies stored.",
      });
    } catch (e) {
      setDialog({ title: "Cookie read failed", body: String(e) });
    }
  };

  const toggleAutoOpen = () => {
    setAutoOpen((v) => {
      const next = !v;
      setPreviewAutoOpen(next);
      return next;
    });
  };

  const filteredLogs = useMemo(() => {
    if (logFilter === "all") return logs;
    return logs.filter((log) => log.stream === logFilter || (logFilter === "error" && log.stream === "stderr"));
  }, [logFilter, logs]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "l") {
      e.preventDefault();
      urlInputRef.current?.focus();
      urlInputRef.current?.select();
    } else if (mod && e.key.toLowerCase() === "r") {
      e.preventDefault();
      refresh();
    } else if (mod && e.key === "[") {
      e.preventDefault();
      goBack();
    } else if (mod && e.key === "]") {
      e.preventDefault();
      goForward();
    } else if (mod && e.altKey && e.key.toLowerCase() === "i") {
      e.preventDefault();
      if (isTauri()) void nativePreview.devtools().catch(() => {});
    }
  };

  const menuBtn = "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] text-muted-foreground transition hover:bg-secondary/60 hover:text-foreground";

  return (
    <div
      ref={rootRef}
      onKeyDown={onKeyDown}
      tabIndex={-1}
      className={cn(
        "relative flex min-h-0 flex-1 flex-col overflow-hidden bg-background/70 outline-none",
        fullscreen && "fixed inset-0 z-50 flex-1 bg-background",
      )}
    >
      {/* Toolbar — essentials inline, the rest in the ⋯ overflow menu */}
      <div className="flex shrink-0 items-center gap-1 border-b border-border px-2 py-1">
        <Button
          size="sm"
          variant="ghost"
          className="h-6 w-6 p-0"
          title={status?.status === "running" ? "Stop app preview" : "Start app preview"}
          onClick={() => void (status?.status === "running" ? stop() : start())}
          disabled={loading || status?.status === "starting"}
        >
          {loading || status?.status === "starting" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : status?.status === "running" ? (
            <Square className="h-3.5 w-3.5" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
        </Button>
        <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="Restart app preview" onClick={() => void restart()} disabled={loading}>
          <RotateCcw className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="Back" onClick={goBack} disabled={!activeUrl}>
          <ArrowLeft className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="Forward" onClick={goForward} disabled={!activeUrl}>
          <ArrowRight className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="Reload browser" onClick={refresh} disabled={!activeUrl}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>

        {/* Status dot */}
        <span
          className={cn("h-2 w-2 shrink-0 rounded-full", statusDot(status?.status ?? "stopped"), status?.status === "starting" && "animate-pulse")}
          title={`${status?.status ?? "stopped"}${status?.kind ? ` · ${status.kind}` : ""}${status?.port ? ` · :${status.port}` : ""}${status?.error ? ` · ${status.error}` : ""}`}
        />

        <form
          className="flex min-w-0 flex-1 items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            navigate();
          }}
        >
          {activeUrl &&
            (loading ? (
              <Loader2 className="h-3 w-3 shrink-0 animate-spin text-muted-foreground/60" />
            ) : activeUrl.startsWith("https://") ? (
              <Lock className="h-3 w-3 shrink-0 text-emerald-400/70" />
            ) : (
              <Globe className="h-3 w-3 shrink-0 text-muted-foreground/50" />
            ))}
          <div className="group/address relative min-w-0 flex-1">
            <input
              ref={urlInputRef}
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              placeholder="Search or enter URL"
              list={devServers.length ? `dev-servers-${slug}` : undefined}
              className="h-7 w-full rounded-md border border-transparent bg-transparent px-2 pr-7 font-mono-ui text-[11px] text-foreground outline-none transition-colors hover:bg-muted/40 focus:border-border focus:bg-background"
            />
            {activeUrl && (
              <button
                type="button"
                className="absolute inset-y-0 right-1 my-auto flex h-5 w-5 items-center justify-center rounded-sm text-muted-foreground opacity-0 transition-opacity hover:bg-muted hover:text-foreground group-hover/address:opacity-100 focus:opacity-100"
                title="Open in browser"
                onClick={() => void api.openExternalUrl(activeUrl)}
              >
                <ExternalLink className="h-3 w-3" />
              </button>
            )}
          </div>
          {devServers.length > 0 && (
            <datalist id={`dev-servers-${slug}`}>
              {devServers.map((s) => (
                <option key={s.port} value={s.url}>
                  dev server :{s.port}
                </option>
              ))}
            </datalist>
          )}
        </form>

        {/* Device preset switcher */}
        <DeviceMenu device={device} onSelect={setDevice} />

        {streamedMode && (
          <>
            {/* Element picker: click an element to insert a reference into chat */}
            <Button
              size="sm"
              variant="ghost"
              className={cn("h-6 w-6 p-0", picking && "bg-primary/20 text-primary")}
              title={picking ? "Picking… click an element" : "Pick an element → chat"}
              onClick={() => setPicking((v) => !v)}
            >
              <MousePointerClick className="h-3.5 w-3.5" />
            </Button>
            {/* Take-over / pause: grab control of the shared session */}
            <Button
              size="sm"
              variant="ghost"
              className={cn("h-6 w-6 p-0", takeover && "bg-amber-500/20 text-amber-400")}
              title={takeover ? "You have control — hand back to agent" : "Take control (pause agent)"}
              onClick={toggleTakeover}
            >
              <Hand className="h-3.5 w-3.5" />
            </Button>
          </>
        )}

        {/* Pop-out / fullscreen the preview region */}
        <Button
          size="sm"
          variant="ghost"
          className={cn("h-6 w-6 p-0", fullscreen && "bg-secondary text-foreground")}
          title={fullscreen ? "Exit fullscreen" : "Pop out / fullscreen"}
          onClick={() => setFullscreen((v) => !v)}
        >
          {fullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </Button>

        {/* Overflow menu */}
        <div ref={menuRef} className="relative">
          <Button
            size="sm"
            variant="ghost"
            className={cn("h-6 w-6 p-0", showMenu && "bg-secondary text-foreground")}
            title="More"
            onClick={() => setShowMenu((v) => !v)}
          >
            <MoreHorizontal className="h-3.5 w-3.5" />
          </Button>
          {showMenu && (
            <div className="absolute right-0 top-7 z-30 min-w-[200px] overflow-hidden rounded-md border border-border bg-popover py-1 shadow-lg">
              <div className="flex items-center gap-2 px-2.5 py-1.5">
                <input
                  value={portOverride}
                  onChange={(e) => setPortOverride(e.target.value.replace(/[^0-9]/g, ""))}
                  placeholder="port"
                  title="Pin a port (overrides auto-detection on start/restart)"
                  inputMode="numeric"
                  className="h-6 w-16 rounded-sm border border-input bg-muted/40 px-1.5 text-center font-mono-ui text-[11px] text-foreground outline-none focus:border-primary/60"
                />
                <span className="text-[11px] text-muted-foreground">Pin port</span>
              </div>
              <button type="button" className={menuBtn} onClick={() => { setPrivateMode((v) => !v); }}>
                <EyeOff className="h-3.5 w-3.5" />
                <span className="flex-1">Private session</span>
                {privateMode && <Check className="h-3.5 w-3.5 text-emerald-400" />}
              </button>
              <button type="button" className={menuBtn} onClick={toggleAutoOpen}>
                <Play className="h-3.5 w-3.5" />
                <span className="flex-1">Auto-open on ready</span>
                {autoOpen && <Check className="h-3.5 w-3.5 text-emerald-400" />}
              </button>
              {streamedMode && (
                <button type="button" className={menuBtn} onClick={toggleDarkEmulation}>
                  <Moon className="h-3.5 w-3.5" />
                  <span className="flex-1">Emulate dark mode</span>
                  {darkEmulation && <Check className="h-3.5 w-3.5 text-emerald-400" />}
                </button>
              )}
              {streamedMode && (
                <button type="button" className={menuBtn} onClick={screenshotToChat}>
                  <Camera className="h-3.5 w-3.5" />
                  <span className="flex-1">Send screenshot to chat</span>
                </button>
              )}
              {streamedMode && (
                <button type="button" className={menuBtn} onClick={recordFlow} disabled={recording}>
                  {recording ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Video className="h-3.5 w-3.5" />}
                  <span className="flex-1">{recording ? "Recording…" : "Record flow (GIF)"}</span>
                </button>
              )}
              <button type="button" className={menuBtn} onClick={() => void showCookies()}>
                <Cookie className="h-3.5 w-3.5" />
                <span className="flex-1">View cookies</span>
              </button>
              <button type="button" className={menuBtn} onClick={clearBrowsingData}>
                <Trash2 className="h-3.5 w-3.5" />
                <span className="flex-1">Clear browsing data</span>
              </button>
              <button type="button" className={menuBtn} onClick={() => { setShowMenu(false); if (activeUrl) void api.openExternalUrl(activeUrl); }} disabled={!activeUrl}>
                <ExternalLink className="h-3.5 w-3.5" />
                <span className="flex-1">Open externally</span>
              </button>
              <button type="button" className={menuBtn} onClick={() => { setShowLogs((v) => !v); setShowMenu(false); }}>
                <Terminal className="h-3.5 w-3.5" />
                <span className="flex-1">Toggle logs</span>
                {showLogs && <Check className="h-3.5 w-3.5 text-emerald-400" />}
              </button>
              <button type="button" className={menuBtn} onClick={() => { setShowActionLog((v) => !v); setShowMenu(false); }}>
                <ScrollText className="h-3.5 w-3.5" />
                <span className="flex-1">Agent action log</span>
                {showActionLog && <Check className="h-3.5 w-3.5 text-emerald-400" />}
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Tab strip (streamed backend only; degrades to single-tab silently) */}
      {streamedMode && tabs.length > 0 && (
        <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-background/60 px-2 py-1">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              className={cn(
                "group flex max-w-[180px] shrink-0 items-center gap-1 rounded-sm border px-2 py-0.5 text-[11px]",
                tab.active
                  ? "border-primary/50 bg-secondary text-foreground"
                  : "border-border bg-muted/30 text-muted-foreground hover:text-foreground",
              )}
            >
              <button
                type="button"
                className="min-w-0 flex-1 truncate text-left"
                title={tab.url}
                onClick={() => !tab.active && switchTab(tab.id)}
              >
                {tab.title || hostOf(tab.url) || "New tab"}
              </button>
              {tabs.length > 1 && (
                <button
                  type="button"
                  className="shrink-0 opacity-50 hover:opacity-100"
                  title="Close tab"
                  onClick={() => closeTab(tab.id)}
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            className="shrink-0 rounded-sm p-0.5 text-muted-foreground hover:bg-muted/40 hover:text-foreground"
            title="New tab"
            onClick={openTab}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      <div className="relative min-h-0 flex-1 bg-black/20">
        {previewPending ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-xs text-muted-foreground/70">
            <Loader2 className="h-5 w-5 animate-spin text-amber-300" />
            <div className="font-mono-ui text-[11px]">
              Waiting for dev server{activeUrl ? ` at ${hostOf(activeUrl)}` : ""}…
            </div>
          </div>
        ) : frameSrc ? (
          <div className="mx-auto h-full" style={deviceWidth ? { maxWidth: deviceWidth } : undefined}>
            {isTauri() ? (
              // Desktop: a real native child webview overlays this region.
              <NativePreview slug={slug} url={frameSrc} persistent={!privateMode} visible={visible} />
            ) : !isDirectPreviewUrl(frameSrc) ? (
              // Web: external sites can't be iframed; stream a server-side browser.
              <StreamedBrowser slug={slug} url={frameSrc} persistent={!privateMode} onTitle={setPageTitle} />
            ) : (
              <iframe
                ref={iframeRef}
                title="Workspace browser"
                src={frameSrc}
                className="h-full w-full border-0 bg-white"
                sandbox="allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
              />
            )}
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-xs text-muted-foreground/70">
            <div className="rounded-sm border border-border bg-card/50 px-3 py-2 text-center font-mono-ui text-[11px]">
              {status?.kind ? (
                <>Detected <span className="text-foreground">{status.kind}</span> app{status?.command ? <> — <span className="text-foreground">{status.command}</span></> : null}</>
              ) : (
                "No preview yet"
              )}
            </div>
            <p className="max-w-xs text-[11px] leading-relaxed text-muted-foreground/60">
              Start the app, enter a URL above, or select a detected local server.
            </p>
            <Button size="sm" className="h-7 gap-1.5 text-xs" onClick={() => void start()} disabled={loading}>
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Globe className="h-3.5 w-3.5" />}
              Start App
            </Button>
          </div>
        )}
        {/* Element-picker capture overlay: maps a click to viewport coords. */}
        {streamedMode && picking && (
          <div
            className="absolute inset-0 z-20 cursor-crosshair bg-primary/5"
            title="Click an element to insert a reference into chat"
            onClick={(e) => {
              const target = e.currentTarget;
              const rect = target.getBoundingClientRect();
              // Map to the 1280×800 streamed viewport (object-contain letterbox).
              const vw = deviceWidth ?? 1280;
              const point = { x: ((e.clientX - rect.left) / rect.width) * vw, y: ((e.clientY - rect.top) / rect.height) * 800 };
              onPickElement(Math.round(point.x), Math.round(point.y));
            }}
          >
            <div className="pointer-events-none absolute left-1/2 top-2 -translate-x-1/2 rounded-sm bg-primary px-2 py-0.5 text-[10px] font-medium text-primary-foreground">
              Click an element to send it to chat
            </div>
          </div>
        )}

        {/* Take-over banner: the user holds control of the shared session. */}
        {streamedMode && takeover && (
          <div className="pointer-events-none absolute right-2 top-2 z-20 flex items-center gap-1.5 rounded-sm bg-amber-500/90 px-2 py-0.5 text-[10px] font-medium text-black">
            <Hand className="h-3 w-3" /> You have control — agent paused
          </div>
        )}

        {/* Follow-agent toast: the agent's most recent browser action. */}
        {streamedMode && agentAction && !takeover && (
          <div className="pointer-events-none absolute left-1/2 top-2 z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-primary/90 px-2.5 py-0.5 text-[10px] font-medium text-primary-foreground shadow">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
            Agent {agentAction.action}
            {agentAction.ref ? ` ${agentAction.ref}` : ""}
          </div>
        )}

        {(pageTitle || lastRefreshReason) && (
          <div className="pointer-events-none absolute bottom-1 left-2 flex items-center gap-2 rounded-sm bg-background/70 px-1.5 py-0.5 font-mono-ui text-[10px] text-muted-foreground/70 backdrop-blur">
            {activeUrl && faviconUrl(activeUrl) && (
              <img src={faviconUrl(activeUrl)} alt="" className="h-3 w-3 rounded-[2px]" onError={(e) => (e.currentTarget.style.display = "none")} />
            )}
            {(pageTitle || hostOf(activeUrl)) && <span className="max-w-[200px] truncate text-foreground/70">{pageTitle || hostOf(activeUrl)}</span>}
          </div>
        )}
      </div>

      {showLogs && (
        <div className="flex max-h-44 shrink-0 flex-col overflow-hidden border-t border-border bg-black/30">
          <div className="flex shrink-0 items-center gap-1 border-b border-border/60 px-2 py-1">
            {(["all", "server", "console", "network", "error"] as const).map((filter) => (
              <button
                key={filter}
                type="button"
                onClick={() => setLogFilter(filter)}
                className={cn(
                  "rounded-sm px-1.5 py-0.5 font-mono-ui text-[10px] uppercase tracking-[0.08em] transition",
                  logFilter === filter ? "bg-secondary text-foreground" : "text-muted-foreground/60 hover:text-foreground",
                )}
              >
                {filter}
              </button>
            ))}
            <button
              type="button"
              className="ml-auto rounded-sm px-1.5 py-0.5 font-mono-ui text-[10px] uppercase tracking-[0.08em] text-muted-foreground/60 hover:text-foreground"
              onClick={() => setLogs([])}
            >
              clear
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 py-1 font-mono text-[10px] leading-4 text-muted-foreground">
            {filteredLogs.length ? filteredLogs.map((log, idx) => (
              <div key={`${log.ts}-${idx}`} className="flex gap-2">
                <span className="shrink-0 text-muted-foreground/40">{shortTime(log.ts)}</span>
                <span className={cn("shrink-0 uppercase", log.stream === "error" || log.stream === "stderr" ? "text-red-300/80" : "text-amber-300/70")}>{log.stream}</span>
                <span className="min-w-0 whitespace-pre-wrap break-words text-foreground/75">{log.text}</span>
              </div>
            )) : (
              <div className="py-3 text-center text-muted-foreground/50">No browser logs yet.</div>
            )}
            </div>
        </div>
      )}

      {showActionLog && (
        <div className="flex max-h-44 shrink-0 flex-col overflow-hidden border-t border-border bg-black/30">
          <div className="flex shrink-0 items-center gap-1.5 border-b border-border/60 px-2 py-1">
            <ScrollText className="h-3 w-3 text-muted-foreground/60" />
            <span className="font-mono-ui text-[10px] uppercase tracking-[0.08em] text-muted-foreground/70">
              Agent action log
            </span>
            <button
              type="button"
              className="ml-auto rounded-sm px-1.5 py-0.5 font-mono-ui text-[10px] uppercase tracking-[0.08em] text-muted-foreground/60 hover:text-foreground"
              onClick={() => setShowActionLog(false)}
            >
              close
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-2 py-1 font-mono text-[10px] leading-4 text-muted-foreground">
            {actions.length ? (
              actions.map((a, idx) => (
                <div key={`${a.ts}-${idx}`} className="flex gap-2">
                  <span className="shrink-0 text-muted-foreground/40">{shortTime(a.ts)}</span>
                  <span
                    className={cn(
                      "shrink-0 uppercase",
                      a.status === "error"
                        ? "text-red-300/80"
                        : a.status === "blocked" || a.status === "paused"
                          ? "text-amber-300/80"
                          : a.status === "needs_confirmation"
                            ? "text-sky-300/80"
                            : "text-emerald-300/70",
                    )}
                  >
                    {a.action}
                  </span>
                  <span className="min-w-0 whitespace-pre-wrap break-words text-foreground/70">
                    {(a.detail?.url as string) ||
                      (a.detail?.ref as string) ||
                      (a.detail?.reason as string) ||
                      a.status}
                  </span>
                </div>
              ))
            ) : (
              <div className="py-3 text-center text-muted-foreground/50">No agent actions recorded yet.</div>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={dialog !== null}
        title={dialog?.title ?? ""}
        body={dialog?.body}
        confirmLabel={dialog?.confirmLabel}
        destructive={dialog?.destructive}
        onConfirm={dialog?.onConfirm}
        onClose={() => setDialog(null)}
      />
    </div>
  );
}

// Compact device-preset dropdown.
function DeviceMenu({ device, onSelect }: { device: DeviceId; onSelect: (d: DeviceId) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const active = DEVICES.find((d) => d.id === device) ?? DEVICES[0];

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        title="Viewport size"
        onClick={() => setOpen((v) => !v)}
        className={cn("flex h-6 items-center gap-0.5 rounded px-1 text-muted-foreground transition hover:bg-secondary hover:text-foreground", open && "bg-secondary text-foreground")}
      >
        <active.Icon className="h-3.5 w-3.5" />
        <ChevronDown className="h-3 w-3" />
      </button>
      {open && (
        <div className="absolute right-0 top-7 z-30 min-w-[150px] overflow-hidden rounded-md border border-border bg-popover py-1 shadow-lg">
          {DEVICES.map((d) => (
            <button
              key={d.id}
              type="button"
              onClick={() => { onSelect(d.id); setOpen(false); }}
              className={cn(
                "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] transition",
                d.id === device ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
              )}
            >
              <d.Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="flex-1">{d.label}</span>
              {d.width && <span className="font-mono-ui text-[10px] text-muted-foreground/60">{d.width}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
