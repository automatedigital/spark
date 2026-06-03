import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Cookie,
  EyeOff,
  ExternalLink,
  Globe,
  Lock,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Square,
  Terminal,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  WorkspacePreviewEvent,
  WorkspacePreviewLog,
  WorkspacePreviewStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { isTauri } from "@/sidecar";
import { StreamedBrowser } from "./StreamedBrowser";
import { NativePreview } from "./NativePreview";
import { nativePreview } from "@/lib/nativePreview";

/** Loopback URLs render fine in an iframe; external origins are blocked by X-Frame-Options/CSP. */
function isLoopbackUrl(url: string): boolean {
  try {
    const host = new URL(url).hostname;
    return host === "127.0.0.1" || host === "localhost" || host === "::1" || host === "[::1]";
  } catch {
    return false;
  }
}

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

function statusTone(status: WorkspacePreviewStatus["status"]): string {
  if (status === "running") return "text-emerald-300";
  if (status === "starting") return "text-amber-300";
  if (status === "failed") return "text-red-300";
  return "text-muted-foreground";
}

function shortTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function WorkspacePreviewPanel({ slug }: { slug: string }) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const urlInputRef = useRef<HTMLInputElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
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

  const activeUrl = status?.url ?? "";

  useEffect(() => {
    setFrameSrc(activeUrl);
    setPageTitle("");
  }, [activeUrl]);

  const reloadFrame = useCallback(() => {
    if (isTauri()) {
      // Native webview: re-navigate to the current URL to reload.
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

  const stop = async () => {
    setLoading(true);
    try {
      setStatus(await api.stopWorkspacePreview(slug));
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
    if (frameSrc && !isLoopbackUrl(frameSrc)) return void api.streamBrowserInput(slug, { type: "back" }).catch(() => {});
    try {
      iframeRef.current?.contentWindow?.history.back();
    } catch {
      /* cross-origin */
    }
  };

  const goForward = () => {
    if (isTauri()) return void nativePreview.forward().catch(() => {});
    if (frameSrc && !isLoopbackUrl(frameSrc)) return void api.streamBrowserInput(slug, { type: "forward" }).catch(() => {});
    try {
      iframeRef.current?.contentWindow?.history.forward();
    } catch {
      /* cross-origin */
    }
  };

  const navigate = async () => {
    const trimmed = urlInput.trim();
    if (!trimmed) return;
    // Guard against silently driving the browser to an arbitrary external
    // origin: confirm before navigating anywhere that isn't local loopback.
    const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
    if (!isLoopbackUrl(withScheme)) {
      let host = withScheme;
      try {
        host = new URL(withScheme).host;
      } catch {
        /* keep raw */
      }
      if (!window.confirm(`Navigate the preview browser to external site:\n\n${host}\n\nContinue?`)) {
        return;
      }
    }
    setLoading(true);
    try {
      const next = await api.navigateWorkspacePreview(slug, trimmed);
      setStatus(next);
    } finally {
      setLoading(false);
    }
  };

  const refresh = () => {
    setLastRefreshReason("manual");
    reloadFrame();
    void api.refreshWorkspacePreview(slug).catch(() => {});
  };

  const clearBrowsingData = async () => {
    if (!window.confirm("Clear all browsing data and sign out of all sites for this workspace?")) return;
    try {
      if (isTauri()) await nativePreview.clearData();
      else await api.clearStreamBrowser(slug);
    } catch (e) {
      console.error("clear browsing data", e);
    }
  };

  const showCookies = async () => {
    try {
      const cookies = isTauri()
        ? await nativePreview.cookies()
        : (await api.streamBrowserCookies(slug)).cookies;
      const byDomain = new Map<string, number>();
      for (const c of cookies) byDomain.set(c.domain, (byDomain.get(c.domain) ?? 0) + 1);
      const summary = [...byDomain.entries()].map(([d, n]) => `${d}: ${n}`).join("\n");
      window.alert(cookies.length ? `Cookies (${cookies.length}):\n\n${summary}` : "No cookies stored.");
    } catch (e) {
      window.alert(`Cookie read failed: ${String(e)}`);
    }
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

  return (
    <div
      ref={rootRef}
      onKeyDown={onKeyDown}
      tabIndex={-1}
      className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background/70 outline-none"
    >
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
        <form
          className="flex min-w-0 flex-1 items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            void navigate();
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
          <input
            ref={urlInputRef}
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            placeholder="Search or enter URL"
            className="h-6 w-full rounded-sm border border-input bg-muted/40 px-2 font-mono-ui text-[11px] text-foreground outline-none transition focus:border-primary/60"
          />
        </form>
        <input
          value={portOverride}
          onChange={(e) => setPortOverride(e.target.value.replace(/[^0-9]/g, ""))}
          placeholder="port"
          title="Pin a port (overrides auto-detection on start/restart)"
          inputMode="numeric"
          className="h-6 w-12 shrink-0 rounded-sm border border-input bg-muted/40 px-1.5 text-center font-mono-ui text-[11px] text-foreground outline-none transition focus:border-primary/60"
        />
        <Button
          size="sm"
          variant="ghost"
          className={cn("h-6 w-6 p-0", privateMode && "bg-secondary text-foreground")}
          title={privateMode ? "Private session (nothing saved) — click for persistent" : "Persistent session — click for private"}
          onClick={() => setPrivateMode((v) => !v)}
        >
          <EyeOff className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="View cookies" onClick={() => void showCookies()}>
          <Cookie className="h-3.5 w-3.5" />
        </Button>
        <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="Clear browsing data" onClick={() => void clearBrowsingData()}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 w-6 p-0"
          title="Open externally"
          onClick={() => activeUrl && void api.openExternalUrl(activeUrl)}
          disabled={!activeUrl}
        >
          <ExternalLink className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className={cn("h-6 w-6 p-0", showLogs && "bg-secondary text-foreground")}
          title="Toggle logs"
          onClick={() => setShowLogs((v) => !v)}
        >
          <Terminal className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex shrink-0 items-center gap-2 border-b border-border px-2 py-1 font-mono-ui text-[10px]">
        <span className={cn("uppercase tracking-[0.12em]", statusTone(status?.status ?? "stopped"))}>
          {status?.status ?? "stopped"}
        </span>
        {status?.kind && <span className="text-muted-foreground/60">{status.kind}</span>}
        {status?.port && <span className="text-muted-foreground/60">:{status.port}</span>}
        {activeUrl && faviconUrl(activeUrl) && (
          <img
            src={faviconUrl(activeUrl)}
            alt=""
            className="h-3 w-3 shrink-0 rounded-[2px]"
            onError={(e) => (e.currentTarget.style.display = "none")}
          />
        )}
        {(pageTitle || hostOf(activeUrl)) && (
          <span className="min-w-0 max-w-[40%] truncate text-foreground/70">{pageTitle || hostOf(activeUrl)}</span>
        )}
        {lastRefreshReason && <span className="text-muted-foreground/50">refresh:{lastRefreshReason}</span>}
        {status?.error && <span className="min-w-0 flex-1 truncate text-red-300/80">{status.error}</span>}
      </div>

      <div className="relative min-h-0 flex-1 bg-black/20">
        {frameSrc && isTauri() ? (
          // Desktop: a real native child webview overlays this region — handles
          // local previews and external sites alike, with persistent logins.
          <NativePreview slug={slug} url={frameSrc} persistent={!privateMode} />
        ) : frameSrc && !isLoopbackUrl(frameSrc) ? (
          // Web: external sites can't be iframed (X-Frame-Options/CSP); stream a
          // real server-side browser instead so they render with live input.
          <StreamedBrowser slug={slug} url={frameSrc} persistent={!privateMode} onTitle={setPageTitle} />
        ) : frameSrc ? (
          <iframe
            ref={iframeRef}
            title="Workspace browser"
            src={frameSrc}
            className="h-full w-full border-0 bg-white"
            sandbox="allow-forms allow-modals allow-popups allow-same-origin allow-scripts"
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-xs text-muted-foreground/70">
            <div className="rounded-sm border border-border bg-card/50 px-3 py-2 font-mono-ui text-[11px]">
              No browser page
            </div>
            <Button size="sm" className="h-7 gap-1.5 text-xs" onClick={() => void start()} disabled={loading}>
              {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Globe className="h-3.5 w-3.5" />}
              Start App
            </Button>
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
    </div>
  );
}
