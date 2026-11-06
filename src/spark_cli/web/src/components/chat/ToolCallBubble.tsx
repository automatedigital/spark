import { useEffect, useRef, useState } from "react";
import { Bot, ChevronDown, ChevronRight, Wrench, Globe, Database, Terminal, FileText, Loader2, Paperclip, Copy } from "lucide-react";
import { apiConnectionGeneration } from "@/lib/apiHelpers";
import { readToolResult, downloadToolResult, type ToolResultPage } from "@/lib/toolResultClient";
import { detectOutputType } from "@/lib/detectOutputType";

// Detect file paths in tool result text (e.g. "Saved to /path/to/file.py")
const PATH_RE = /(?:saved to|written to|output:|created:|file:|path:)\s+([^\s,\n"']+\.[a-zA-Z]{1,6})/gi;

function extractOutputPaths(text: string): string[] {
  const paths: string[] = [];
  let m: RegExpExecArray | null;
  PATH_RE.lastIndex = 0;
  while ((m = PATH_RE.exec(text)) !== null) {
    paths.push(m[1]);
  }
  return [...new Set(paths)];
}

const TOOL_FAMILIES: Record<string, { color: string; icon: typeof Wrench }> = {
  bash: { color: "amber", icon: Terminal },
  run_command: { color: "amber", icon: Terminal },
  shell: { color: "amber", icon: Terminal },
  fetch_url: { color: "purple", icon: Globe },
  web_search: { color: "purple", icon: Globe },
  browse: { color: "purple", icon: Globe },
  read_file: { color: "blue", icon: FileText },
  write_file: { color: "blue", icon: FileText },
  list_files: { color: "blue", icon: FileText },
  read_memory: { color: "green", icon: Database },
  write_memory: { color: "green", icon: Database },
  search_memory: { color: "green", icon: Database },
  delegate_task: { color: "blue", icon: Bot },
};

const COLOR_CLASSES: Record<string, { border: string; bg: string; text: string }> = {
  amber: { border: "border-warning/30", bg: "bg-warning/5", text: "text-warning/70" },
  purple: { border: "border-purple-400/30", bg: "bg-purple-500/5", text: "text-purple-400/70" },
  blue: { border: "border-blue-400/30", bg: "bg-blue-500/5", text: "text-blue-400/70" },
  green: { border: "border-success/30", bg: "bg-success/5", text: "text-success/70" },
};

const LARGE_RESULT_CHARS = 12_000;

function formatBytes(chars: number): string {
  if (chars < 1000) return `${chars} chars`;
  if (chars < 1_000_000) return `${(chars / 1000).toFixed(chars < 10_000 ? 1 : 0)}K chars`;
  return `${(chars / 1_000_000).toFixed(1)}M chars`;
}

function formatSeconds(seconds: number): string {
  return `${Math.max(0, seconds).toFixed(1)}s`;
}

function ResultPreview({ result, safeMode }: { result: string; safeMode?: boolean }) {
  const [fullscreen, setFullscreen] = useState(false);
  const trimmed = result.trim();
  const detected = safeMode || result.length > LARGE_RESULT_CHARS ? { kind: "text" as const } : detectOutputType(trimmed);

  if (detected.kind === "image") {
    return (
      <>
        <img
          src={detected.url}
          alt={trimmed}
          className="max-h-48 rounded cursor-pointer object-contain"
          onClick={() => setFullscreen(true)}
        />
        {fullscreen && (
          <div
            className="fixed inset-0 z-[200] flex items-center justify-center bg-black/80"
            onClick={() => setFullscreen(false)}
          >
            <img src={detected.url} alt={trimmed} className="max-h-[90vh] max-w-[90vw] rounded object-contain" />
          </div>
        )}
      </>
    );
  }
  if (detected.kind === "audio") {
    return <audio controls src={detected.url} className="w-full max-w-xs" />;
  }
  if (detected.kind === "video") {
    return <video controls src={detected.url} className="max-h-48 rounded w-full" />;
  }
  return (
    <pre className="text-[11px] overflow-x-auto whitespace-pre-wrap font-mono text-foreground/90 max-h-[360px] overflow-y-auto">
      {result}
    </pre>
  );
}

function getArgPreview(name: string, args: Record<string, unknown>): string | null {
  const lname = name.toLowerCase();
  if (lname.includes("bash") || lname.includes("shell") || lname.includes("command")) {
    const cmd = args.command ?? args.cmd ?? args.script;
    if (typeof cmd === "string") return cmd.slice(0, 80);
  }
  if (lname.includes("file") || lname.includes("read") || lname.includes("write") || lname.includes("list")) {
    const p = args.path ?? args.file ?? args.filename;
    if (typeof p === "string") return p;
  }
  if (lname.includes("url") || lname.includes("fetch") || lname.includes("browse")) {
    const url = args.url ?? args.href;
    if (typeof url === "string") return url.slice(0, 80);
  }
  if (lname.includes("search") || lname.includes("query")) {
    const q = args.query ?? args.q ?? args.term;
    if (typeof q === "string") return `"${q.slice(0, 60)}"`;
  }
  // Fallback: first string arg value
  for (const v of Object.values(args)) {
    if (typeof v === "string" && v.length > 0) return v.slice(0, 80);
  }
  return null;
}

function displayToolName(name: string, done?: boolean): string {
  if (name === "delegate_task") return done ? "sub-agent" : "running sub-agent";
  return name;
}

export function ToolCallBubble({
  sessionId,
  toolCallId,
  name,
  args,
  result,
  resultTruncated,
  done,
  startedAt,
  endedAt,
  durationSeconds,
  repeatCount,
  safeMode,
  onAttachPath,
  onFetchFullResult,
}: {
  sessionId?: string | null;
  toolCallId?: string;
  name: string;
  args: Record<string, unknown>;
  result?: string;
  resultTruncated?: boolean;
  done?: boolean;
  startedAt?: number;
  endedAt?: number;
  durationSeconds?: number;
  repeatCount?: number;
  safeMode?: boolean;
  onAttachPath?: (path: string) => void;
  onFetchFullResult?: () => Promise<string | null>;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [displayResult, setDisplayResult] = useState(result);
  const [loadingFullResult, setLoadingFullResult] = useState(false);
  const [fullResultError, setFullResultError] = useState<string | null>(null);

  const [page, setPage] = useState<ToolResultPage | null>(null);
  const request = useRef<AbortController | null>(null);
  const generation = apiConnectionGeneration();
  useEffect(() => {
    request.current?.abort();
    setDisplayResult(result?.slice(0, 65536));
    setPage(null);
    setOpen(false);
    setLoadingFullResult(false);
    setFullResultError(null);
    return () => request.current?.abort();
  }, [result, sessionId, toolCallId, generation]);

  const loadPage = async (previous?: ToolResultPage) => {
    if (!sessionId || !toolCallId) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const epoch = apiConnectionGeneration();
    setLoadingFullResult(true);
    setFullResultError(null);
    try {
      const next = await readToolResult(sessionId, toolCallId, controller.signal, previous);
      if (controller.signal.aborted || epoch !== apiConnectionGeneration()) return;
      setPage(next);
      // Replace the visible page; never accumulate a multi-megabyte DOM.
      setDisplayResult(next.content);
    } catch (error) {
      if (!controller.signal.aborted) setFullResultError(error instanceof Error ? error.message : String(error));
    } finally {
      if (!controller.signal.aborted) setLoadingFullResult(false);
    }
  };

  const download = async () => {
    if (!(sessionId && toolCallId && page) && !onFetchFullResult) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const epoch = apiConnectionGeneration();
    setLoadingFullResult(true);
    setFullResultError(null);
    try {
      const blob = sessionId && toolCallId && page
        ? await downloadToolResult(sessionId, toolCallId, page, controller.signal)
        : new Blob([await onFetchFullResult?.() ?? ""], { type: "text/plain" });
      if (controller.signal.aborted || epoch !== apiConnectionGeneration()) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "tool-result.txt";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      if (!controller.signal.aborted) setFullResultError(error instanceof Error ? error.message : String(error));
    } finally {
      if (!controller.signal.aborted) setLoadingFullResult(false);
    }
  };

  const lname = name.toLowerCase();
  const family = Object.keys(TOOL_FAMILIES).find((k) => lname.includes(k));
  const familyInfo = family ? TOOL_FAMILIES[family] : null;
  const color = done
    ? (familyInfo ? familyInfo.color : "green")
    : (familyInfo ? familyInfo.color : "amber");
  const colors = done
    ? { border: "border-success/30", bg: "bg-success/5", text: "text-success/70" }
    : COLOR_CLASSES[color] ?? { border: "border-warning/30", bg: "bg-warning/5", text: "text-warning/70" };

  const Icon = familyInfo?.icon ?? Wrench;

  const elapsed =
    done && typeof durationSeconds === "number"
      ? formatSeconds(durationSeconds)
      : done && typeof startedAt === "number" && typeof endedAt === "number"
      ? formatSeconds(endedAt - startedAt)
      : null;

  const argPreview = getArgPreview(name, args);
  const visibleName = displayToolName(name, done);
  const resultSize = displayResult ? formatBytes(displayResult.length) : null;
  const isLargeResult = (displayResult?.length ?? 0) > LARGE_RESULT_CHARS || Boolean(resultTruncated);

  let argsStr: string;
  try {
    argsStr = JSON.stringify(args, null, 2);
  } catch {
    argsStr = String(args);
  }

  const copyResult = () => {
    if (!displayResult) return;
    void navigator.clipboard.writeText(displayResult).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  const toggleOpen = () => {
    const nextOpen = !open;
    setOpen(nextOpen);
    if (!nextOpen) {
      request.current?.abort();
      setLoadingFullResult(false);
    } else if (sessionId && toolCallId) {
      void loadPage();
    }

  };

  return (
    <div className="overflow-hidden rounded-md bg-foreground/[0.035] text-xs">
      <button
        type="button"
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 cursor-pointer hover:bg-foreground/5 transition-colors text-left"
        onClick={toggleOpen}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <Icon className={`h-3.5 w-3.5 shrink-0 ${colors.text}`} />
        <span className="font-mono font-medium text-foreground">{visibleName}</span>
        {!open && argPreview && (
          <span className="text-muted-foreground/60 truncate flex-1 text-[11px] font-mono">
            {argPreview}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2 shrink-0">
          {elapsed && <span className="text-[10px] text-muted-foreground/50">{elapsed}</span>}
          {resultSize && (
            <span className="text-[10px] text-muted-foreground/50">
              {isLargeResult ? `large output · ${resultSize}` : resultSize}
            </span>
          )}
          {repeatCount != null && repeatCount > 0 && (
            <span className="rounded-full bg-warning/20 px-1.5 py-0.5 text-[10px] font-semibold text-warning">
              ×{repeatCount + 1}
            </span>
          )}
          {!done ? (
            <span className={`flex items-center gap-1 text-[10px] text-muted-foreground ${safeMode ? "" : "animate-pulse"}`}>
              <Loader2 className={`h-3 w-3 ${safeMode ? "" : "animate-spin"}`} />
              running
            </span>
          ) : (
            <span className="text-[10px] text-muted-foreground">done</span>
          )}
        </div>
      </button>
      {open && (
        <div className="border-t border-border/45 px-3 py-2 space-y-2">
          <pre className="text-[11px] overflow-x-auto whitespace-pre-wrap font-mono text-muted-foreground max-h-40 overflow-y-auto">
            {argsStr.slice(0, 12000)}
          </pre>
          {((displayResult != null && displayResult !== "") || loadingFullResult || fullResultError || page) && (
            <div>
              <div className="mb-1 flex items-center justify-between gap-2">
                <div className="text-[10px] text-muted-foreground">
                  Result {resultSize ? <span className="text-muted-foreground/50">· {resultSize}</span> : null}
                </div>
                <button
                  type="button"
                  onClick={copyResult}
                  className="inline-flex items-center gap-1 rounded-md bg-foreground/6 px-1.5 py-0.5 text-[10px] text-muted-foreground transition hover:bg-foreground/9 hover:text-foreground"
                  title="Copy visible preview"
                >
                  <Copy className="h-2.5 w-2.5" />
                  {copied ? "Copied" : "Copy preview"}
                </button>
              </div>
              <ResultPreview result={displayResult ?? ""} safeMode={safeMode} />
              {loadingFullResult && (
                <p className="text-[10px] text-muted-foreground/50 mt-0.5">Loading output…</p>
              )}
              {fullResultError && (
                <p className="text-[10px] text-destructive/80 mt-0.5">Could not load output: {fullResultError}</p>
              )}
              {!sessionId && onFetchFullResult && <button type="button" disabled={loadingFullResult} onClick={() => void download()}>Download full output</button>}
              {page && (
                <div className="flex gap-2 items-center text-[10px]">
                  <span>{page.offset}–{page.offset + new TextEncoder().encode(page.content).length} of {page.total_bytes} bytes</span>
                  {page.next_offset !== null && <button type="button" disabled={loadingFullResult} onClick={() => void loadPage(page)}>Next page</button>}
                  <button type="button" disabled={loadingFullResult} onClick={() => void download()}>Download full output</button>
                </div>
              )}
              {onAttachPath && done && (() => {
                const paths = extractOutputPaths((displayResult ?? "").slice(0, LARGE_RESULT_CHARS)).slice(0, 20);
                if (paths.length === 0) return null;
                return (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {paths.map((p) => (
                      <button
                        key={p}
                        type="button"
                        onClick={() => onAttachPath(p)}
                        className="flex items-center gap-1 rounded-md bg-foreground/6 px-1.5 py-0.5 text-[10px] text-muted-foreground transition hover:bg-foreground/9 hover:text-foreground"
                        title={`Attach ${p} to context tray`}
                      >
                        <Paperclip className="h-2.5 w-2.5" />
                        <span className="font-mono truncate max-w-[120px]">{p.split("/").pop()}</span>
                      </button>
                    ))}
                  </div>
                );
              })()}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
