import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ExternalLink,
  Globe,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Square,
  Terminal,
} from "lucide-react";
import { api } from "@/lib/api";
import type {
  WorkspacePreviewEvent,
  WorkspacePreviewLog,
  WorkspacePreviewStatus,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

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
  const eventSourceRef = useRef<EventSource | null>(null);
  const [status, setStatus] = useState<WorkspacePreviewStatus | null>(null);
  const [frameSrc, setFrameSrc] = useState("");
  const [urlInput, setUrlInput] = useState("");
  const [logs, setLogs] = useState<WorkspacePreviewLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [showLogs, setShowLogs] = useState(false);
  const [logFilter, setLogFilter] = useState<"all" | "server" | "console" | "network" | "error">("all");
  const [lastRefreshReason, setLastRefreshReason] = useState<string | null>(null);

  const activeUrl = status?.url ?? "";

  useEffect(() => {
    setFrameSrc(activeUrl);
  }, [activeUrl]);

  const reloadFrame = useCallback(() => {
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

  const start = async () => {
    setLoading(true);
    try {
      const next = await api.startWorkspacePreview(slug);
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
      const next = await api.restartWorkspacePreview(slug);
      setStatus(next);
      setUrlInput(next.url ?? "");
    } finally {
      setLoading(false);
    }
  };

  const navigate = async () => {
    const trimmed = urlInput.trim();
    if (!trimmed) return;
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

  const filteredLogs = useMemo(() => {
    if (logFilter === "all") return logs;
    return logs.filter((log) => log.stream === logFilter || (logFilter === "error" && log.stream === "stderr"));
  }, [logFilter, logs]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-background/70">
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
        <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="Reload browser" onClick={refresh} disabled={!activeUrl}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
        <form
          className="min-w-0 flex-1"
          onSubmit={(e) => {
            e.preventDefault();
            void navigate();
          }}
        >
          <input
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            placeholder="Search or enter URL"
            className="h-6 w-full rounded-sm border border-input bg-muted/40 px-2 font-mono-ui text-[11px] text-foreground outline-none transition focus:border-primary/60"
          />
        </form>
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
        {lastRefreshReason && <span className="text-muted-foreground/50">refresh:{lastRefreshReason}</span>}
        {status?.error && <span className="min-w-0 flex-1 truncate text-red-300/80">{status.error}</span>}
      </div>

      <div className="relative min-h-0 flex-1 bg-black/20">
        {frameSrc ? (
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
