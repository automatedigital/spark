import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench, Globe, Database, Terminal, FileText, Loader2, Paperclip, Copy } from "lucide-react";
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

export function ToolCallBubble({
  name,
  args,
  result,
  resultTruncated,
  done,
  startedAt,
  endedAt,
  repeatCount,
  safeMode,
  onAttachPath,
}: {
  name: string;
  args: Record<string, unknown>;
  result?: string;
  resultTruncated?: boolean;
  done?: boolean;
  startedAt?: number;
  endedAt?: number;
  repeatCount?: number;
  safeMode?: boolean;
  onAttachPath?: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

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
    done && startedAt && endedAt
      ? `${((endedAt - startedAt) / 1000).toFixed(1)}s`
      : null;

  const argPreview = getArgPreview(name, args);
  const resultSize = result ? formatBytes(result.length) : null;
  const isLargeResult = (result?.length ?? 0) > LARGE_RESULT_CHARS;

  let argsStr: string;
  try {
    argsStr = JSON.stringify(args, null, 2);
  } catch {
    argsStr = String(args);
  }

  const copyResult = () => {
    if (!result) return;
    void navigator.clipboard.writeText(result).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="overflow-hidden rounded-md bg-foreground/[0.035] text-xs">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 cursor-pointer hover:bg-foreground/5 transition-colors text-left"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <Icon className={`h-3.5 w-3.5 shrink-0 ${colors.text}`} />
        <span className="font-mono font-medium text-foreground">{name}</span>
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
            {argsStr}
          </pre>
          {result != null && result !== "" && (
            <div>
              <div className="mb-1 flex items-center justify-between gap-2">
                <div className="text-[10px] text-muted-foreground">
                  Result {resultSize ? <span className="text-muted-foreground/50">· {resultSize}</span> : null}
                </div>
                <button
                  type="button"
                  onClick={copyResult}
                  className="inline-flex items-center gap-1 rounded-md bg-foreground/6 px-1.5 py-0.5 text-[10px] text-muted-foreground transition hover:bg-foreground/9 hover:text-foreground"
                  title="Copy full result"
                >
                  <Copy className="h-2.5 w-2.5" />
                  {copied ? "Copied" : "Copy"}
                </button>
              </div>
              <ResultPreview result={result} safeMode={safeMode} />
              {resultTruncated && (
                <p className="text-[10px] text-muted-foreground/50 mt-0.5">Output was truncated before it reached the UI stream.</p>
              )}
              {onAttachPath && done && (() => {
                const paths = extractOutputPaths(result);
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
