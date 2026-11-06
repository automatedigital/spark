import { useCallback, useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { SearchAddon } from "@xterm/addon-search";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { Copy, Eraser, RotateCcw, Search, X } from "lucide-react";
import { api } from "@/lib/api";
import { createTerminalLifecycle, type TerminalStatus } from "@/lib/terminalLifecycle";
import { useWebUITheme } from "@/lib/theme";
import { cn } from "@/lib/utils";


/** Read a theme colour token, falling back to a sane default. */
function cssColor(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/** Derive an xterm palette from the active webui theme's CSS variables so the
 *  terminal matches Slate/Daylight/etc. instead of a hardcoded amber. */
function buildTerminalTheme() {
  const bg = cssColor("--color-card", "#0d0d0d");
  const fg = cssColor("--color-foreground", "#d8d0c0");
  const accent = cssColor("--color-primary", "#FDA632");
  return {
    background: bg,
    foreground: fg,
    cursor: accent,
    cursorAccent: bg,
    selectionBackground: `${accent}44`,
  };
}

export function WorkspaceTerminalPanel({ slug }: { slug: string }) {
  const { theme } = useWebUITheme();
  const terminalHostRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const searchAddonRef = useRef<SearchAddon | null>(null);
  const lifecycleRef = useRef<ReturnType<typeof createTerminalLifecycle> | null>(null);
  const shellRunIdRef = useRef<string | null>(null);
  const resizeTimerRef = useRef<number | null>(null);
  const [shellRunId, setShellRunId] = useState<string | null>(null);
  const [shellStatus, setShellStatus] = useState<TerminalStatus>("connecting");
  const [showFind, setShowFind] = useState(false);
  const [findValue, setFindValue] = useState("");

  const sendResize = useCallback(() => {
    const term = terminalRef.current;
    const fit = fitAddonRef.current;
    const runId = shellRunIdRef.current;
    if (!term || !fit || !runId) return;
    try {
      fit.fit();
      void api.resizeWorkspaceTerminal(slug, runId, term.rows, term.cols).catch(() => {});
    } catch {
      // Terminal may be hidden during pane changes; fit again on next resize/focus.
    }
  }, [slug]);

  useEffect(() => {
    const host = terminalHostRef.current;
    if (!host) return;

    const term = new Terminal({
      allowProposedApi: false,
      convertEol: false,
      cursorBlink: true,
      cursorStyle: "block",
      fontFamily: '"Courier Prime", "SF Mono", Menlo, monospace',
      fontSize: 12,
      lineHeight: 1.25,
      scrollback: 4000,
      theme: buildTerminalTheme(),
    });
    const fit = new FitAddon();
    const search = new SearchAddon();
    terminalRef.current = term;
    fitAddonRef.current = fit;
    searchAddonRef.current = search;
    term.loadAddon(fit);
    term.loadAddon(search);
    term.loadAddon(new WebLinksAddon((_e, uri) => void api.openExternalUrl(uri).catch(() => {})));
    term.open(host);
    term.attachCustomKeyEventHandler((event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f") {
        event.preventDefault();
        setShowFind(true);
        return false;
      }
      event.stopPropagation();
      return true;
    });

    let disposed = false;
    const dataDisposable = term.onData((data) => {
      const runId = shellRunIdRef.current;
      if (!runId) return;
      void api.sendWorkspaceTerminalInput(slug, runId, data).catch((e) => {
        if (!disposed && shellRunIdRef.current === runId) term.writeln(`\r\n\x1b[31mFailed to send input: ${String(e)}\x1b[0m`);
      });
    });

    const lifecycle = createTerminalLifecycle({
      start: () => api.runWorkspaceTerminalCommand(slug),
      stop: (id) => api.stopWorkspaceTerminalRun(slug, id),
      stream: (id) => api.streamWorkspaceTerminalRun(slug, id),
      state: (status, id) => {
        shellRunIdRef.current = id;
        setShellRunId(id);
        setShellStatus(status);
        if (status === "running") { sendResize(); term.focus(); }
      },
      event: (data) => {
        if (data.type === "output" && data.text) term.write(data.text);
        if (data.type === "done") term.writeln(`\r\n[terminal ${data.status}]`);
      },
      error: (message) => { if (!disposed) term.writeln(`\r\n${message}`); },
    });
    lifecycleRef.current = lifecycle;
    lifecycle.restart();

    const observer = new ResizeObserver(() => {
      if (resizeTimerRef.current !== null) window.clearTimeout(resizeTimerRef.current);
      resizeTimerRef.current = window.setTimeout(sendResize, 80);
    });
    observer.observe(host);
    const initialResize = window.setTimeout(sendResize, 30);

    return () => {
      disposed = true;
      lifecycle.retire();
      if (lifecycleRef.current === lifecycle) lifecycleRef.current = null;
      window.clearTimeout(initialResize);
      observer.disconnect();
      dataDisposable.dispose();
      if (resizeTimerRef.current !== null) window.clearTimeout(resizeTimerRef.current);
      shellRunIdRef.current = null;
      terminalRef.current = null;
      fitAddonRef.current = null;
      searchAddonRef.current = null;
      term.dispose();
    };
  }, [sendResize, slug]);

  // Re-skin the live terminal when the webui theme changes.
  useEffect(() => {
    const term = terminalRef.current;
    if (term) term.options.theme = buildTerminalTheme();
  }, [theme]);

  // Restart kills the current shell and starts a fresh one.
  const restart = () => {
    terminalRef.current?.clear();
    lifecycleRef.current?.restart();
  };

  const copySelection = () => {
    const sel = terminalRef.current?.getSelection();
    if (sel) void navigator.clipboard.writeText(sel).catch(() => {});
  };

  const runFind = (next: boolean) => {
    if (!findValue) return;
    if (next) searchAddonRef.current?.findNext(findValue);
    else searchAddonRef.current?.findPrevious(findValue);
  };

  const disconnected = shellStatus === "disconnected";

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="flex h-7 shrink-0 items-center gap-1 border-b border-border px-1.5">
        <span className="font-mono-ui text-[10px] uppercase tracking-[0.12em] text-muted-foreground/70">
          {shellStatus}{shellRunId ? ` · ${shellRunId.slice(-4)}` : ""}
        </span>
        {disconnected && (
          <button
            type="button"
            onClick={() => lifecycleRef.current?.reconnect()}
            className="rounded-sm bg-secondary px-1.5 py-0.5 text-[10px] text-foreground transition hover:bg-secondary/70"
          >
            Reconnect
          </button>
        )}
        <div className="ml-auto flex items-center gap-0.5">
          <button type="button" title="Find (⌘F)" onClick={() => setShowFind((v) => !v)} className={cn("rounded p-1 text-muted-foreground/60 transition hover:bg-secondary hover:text-foreground", showFind && "bg-secondary text-foreground")}>
            <Search className="h-3 w-3" />
          </button>
          <button type="button" title="Copy selection" onClick={copySelection} className="rounded p-1 text-muted-foreground/60 transition hover:bg-secondary hover:text-foreground">
            <Copy className="h-3 w-3" />
          </button>
          <button type="button" title="Clear scrollback" onClick={() => terminalRef.current?.clear()} className="rounded p-1 text-muted-foreground/60 transition hover:bg-secondary hover:text-foreground">
            <Eraser className="h-3 w-3" />
          </button>
          <button type="button" title="Kill & restart shell" onClick={restart} className="rounded p-1 text-muted-foreground/60 transition hover:bg-secondary hover:text-foreground">
            <RotateCcw className="h-3 w-3" />
          </button>
        </div>
      </div>

      {/* Find bar */}
      {showFind && (
        <div className="flex h-7 shrink-0 items-center gap-1.5 border-b border-border bg-background/60 px-2">
          <Search className="h-3 w-3 shrink-0 text-muted-foreground/50" />
          <input
            autoFocus
            value={findValue}
            onChange={(e) => setFindValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") runFind(!e.shiftKey);
              if (e.key === "Escape") { setShowFind(false); terminalRef.current?.focus(); }
            }}
            placeholder="Find in terminal…"
            className="h-5 w-full bg-transparent font-mono-ui text-[11px] text-foreground outline-none placeholder:text-muted-foreground/40"
          />
          <button type="button" title="Previous" onClick={() => runFind(false)} className="text-muted-foreground/60 hover:text-foreground">↑</button>
          <button type="button" title="Next" onClick={() => runFind(true)} className="text-muted-foreground/60 hover:text-foreground">↓</button>
          <button type="button" title="Close" onClick={() => { setShowFind(false); terminalRef.current?.focus(); }} className="text-muted-foreground/60 hover:text-foreground">
            <X className="h-3 w-3" />
          </button>
        </div>
      )}

      <div
        className="spark-terminal-pane relative min-h-0 flex-1 overflow-hidden"
        onMouseDown={() => terminalRef.current?.focus()}
        onClick={() => terminalRef.current?.focus()}
      >
        <div ref={terminalHostRef} className="h-full w-full px-2 py-2" />
      </div>
    </div>
  );
}
