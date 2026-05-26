import { useCallback, useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { api } from "@/lib/api";
import type { WorkspaceTerminalEvent } from "@/lib/api";

export function WorkspaceTerminalPanel({ slug }: { slug: string }) {
  const terminalHostRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const shellRunIdRef = useRef<string | null>(null);
  const resizeTimerRef = useRef<number | null>(null);
  const [shellRunId, setShellRunId] = useState<string | null>(null);
  const [shellStatus, setShellStatus] = useState<"connecting" | "running" | "stopped" | "failed">("connecting");

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
      theme: {
        background: "#0d0d0d",
        foreground: "#d8d0c0",
        cursor: "#FDA632",
        selectionBackground: "#FDA63244",
        black: "#151515",
        red: "#f97316",
        green: "#8fd694",
        yellow: "#FDA632",
        blue: "#8fb4ff",
        magenta: "#cb9cf2",
        cyan: "#8bd7d2",
        white: "#f0ece4",
        brightBlack: "#6b6b60",
        brightRed: "#ff9a5f",
        brightGreen: "#b7e4b7",
        brightYellow: "#ffc875",
        brightBlue: "#b3c8ff",
        brightMagenta: "#dfb5ff",
        brightCyan: "#aee8e4",
        brightWhite: "#ffffff",
      },
    });
    const fit = new FitAddon();
    terminalRef.current = term;
    fitAddonRef.current = fit;
    term.loadAddon(fit);
    term.open(host);
    term.attachCustomKeyEventHandler((event) => {
      event.stopPropagation();
      return true;
    });
    term.writeln("\x1b[2mStarting workspace shell...\x1b[0m");
    setShellStatus("connecting");

    const dataDisposable = term.onData((data) => {
      const runId = shellRunIdRef.current;
      if (!runId) return;
      void api.sendWorkspaceTerminalInput(slug, runId, data).catch((e) => {
        term.writeln(`\r\n\x1b[31mFailed to send input: ${String(e)}\x1b[0m`);
      });
    });

    let cancelled = false;
    void api.runWorkspaceTerminalCommand(slug).then((run) => {
      if (cancelled) return;
      setShellRunId(run.run_id);
      shellRunIdRef.current = run.run_id;
      const source = api.streamWorkspaceTerminalRun(slug, run.run_id);
      eventSourceRef.current = source;
      source.onmessage = (ev) => {
        const data = JSON.parse(ev.data) as WorkspaceTerminalEvent;
        if (data.type === "output") {
          term.write(data.text);
          return;
        }
        if (data.type === "state") {
          setShellStatus(data.status === "running" ? "running" : "connecting");
          if (data.status === "running") {
            window.setTimeout(sendResize, 30);
            term.focus();
          }
          return;
        }
        if (data.type === "done") {
          setShellStatus(data.status === "stopped" ? "stopped" : "failed");
          term.writeln(`\r\n\x1b[2m[terminal ${data.status}${data.exit_code !== null ? `:${data.exit_code}` : ""}]\x1b[0m`);
          source.close();
          if (eventSourceRef.current === source) eventSourceRef.current = null;
        }
      };
      source.onerror = () => {
        setShellStatus("failed");
        term.writeln("\r\n\x1b[31m[terminal stream disconnected]\x1b[0m");
        source.close();
        if (eventSourceRef.current === source) eventSourceRef.current = null;
      };
    }).catch((e) => {
      if (cancelled) return;
      setShellStatus("failed");
      term.writeln(`\r\n\x1b[31mFailed to start shell: ${String(e)}\x1b[0m`);
    });

    const observer = new ResizeObserver(() => {
      if (resizeTimerRef.current !== null) window.clearTimeout(resizeTimerRef.current);
      resizeTimerRef.current = window.setTimeout(sendResize, 80);
    });
    observer.observe(host);
    window.setTimeout(sendResize, 30);

    return () => {
      cancelled = true;
      observer.disconnect();
      dataDisposable.dispose();
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      if (resizeTimerRef.current !== null) window.clearTimeout(resizeTimerRef.current);
      if (shellRunIdRef.current) void api.stopWorkspaceTerminalRun(slug, shellRunIdRef.current).catch(() => {});
      shellRunIdRef.current = null;
      terminalRef.current = null;
      fitAddonRef.current = null;
      term.dispose();
    };
  }, [sendResize, slug]);

  return (
    <div
      className="spark-terminal-pane relative min-h-0 flex-1 overflow-hidden"
      onMouseDown={() => terminalRef.current?.focus()}
      onClick={() => terminalRef.current?.focus()}
    >
      <div ref={terminalHostRef} className="h-full w-full px-2 py-2" />
      <div className="pointer-events-none absolute right-2 top-2 rounded-sm border border-border bg-background/75 px-2 py-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground backdrop-blur">
        {shellStatus}
        {shellRunId ? ` · ${shellRunId.slice(-4)}` : ""}
      </div>
    </div>
  );
}
