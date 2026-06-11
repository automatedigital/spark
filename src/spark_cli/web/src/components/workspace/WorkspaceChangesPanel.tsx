import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FilePlus2,
  FileX2,
  FilePen,
  GitBranch,
  Loader2,
  RotateCcw,
} from "lucide-react";
import { api } from "@/lib/api";
import type { WorkspaceGitFile, WorkspaceGitStatus } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useEventBus } from "@/hooks/useEventBus";
import type { SparkEventEnvelope } from "@/hooks/useEventBus";

function StatusIcon({ status }: { status: WorkspaceGitFile["status"] }) {
  if (status === "added") return <FilePlus2 className="h-3.5 w-3.5 shrink-0 text-emerald-400/80" />;
  if (status === "deleted") return <FileX2 className="h-3.5 w-3.5 shrink-0 text-red-400/80" />;
  return <FilePen className="h-3.5 w-3.5 shrink-0 text-amber-300/80" />;
}

/** Colourise a unified diff line-by-line (add/remove/hunk header). */
function DiffView({ diff }: { diff: string }) {
  const lines = diff.split("\n");
  return (
    <pre className="overflow-x-auto bg-black/20 px-2 py-1.5 font-mono text-[10px] leading-4">
      {lines.map((line, i) => {
        let tone = "text-muted-foreground/75";
        if (line.startsWith("+") && !line.startsWith("+++")) tone = "bg-emerald-500/10 text-emerald-300/90";
        else if (line.startsWith("-") && !line.startsWith("---")) tone = "bg-red-500/10 text-red-300/90";
        else if (line.startsWith("@@")) tone = "text-sky-300/80";
        else if (line.startsWith("diff ") || line.startsWith("index ") || line.startsWith("+++") || line.startsWith("---"))
          tone = "text-muted-foreground/40";
        return (
          <div key={i} className={cn("whitespace-pre", tone)}>{line || " "}</div>
        );
      })}
    </pre>
  );
}

function ChangeRow({ slug, file, onReverted }: { slug: string; file: WorkspaceGitFile; onReverted: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [diff, setDiff] = useState<string | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [confirmRevert, setConfirmRevert] = useState(false);

  const toggle = async () => {
    const next = !expanded;
    setExpanded(next);
    if (next && diff === null) {
      setLoadingDiff(true);
      try {
        const res = await api.getWorkspaceGitDiff(slug, file.path);
        setDiff(res.diff || "(no diff)");
      } catch {
        setDiff("Failed to load diff.");
      } finally {
        setLoadingDiff(false);
      }
    }
  };

  const revert = async () => {
    try {
      await api.revertWorkspaceGitFile(slug, file.path);
      onReverted();
    } catch (e) {
      console.error("Revert failed", e);
    }
  };

  return (
    <div className="border-b border-border/40">
      <div
        className="group flex cursor-pointer items-center gap-1.5 px-2 py-1 text-[11px] transition hover:bg-secondary/50"
        onClick={() => void toggle()}
      >
        <span className="text-muted-foreground/50">
          {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        </span>
        <StatusIcon status={file.status} />
        <span className="min-w-0 flex-1 truncate font-mono-ui text-muted-foreground">{file.path}</span>
        <span className="shrink-0 font-mono-ui text-[10px]">
          {file.adds != null && file.adds > 0 && <span className="text-emerald-400/80">+{file.adds}</span>}
          {file.adds != null && file.dels != null && (file.adds > 0 || file.dels > 0) && " "}
          {file.dels != null && file.dels > 0 && <span className="text-red-400/80">-{file.dels}</span>}
          {file.adds == null && file.dels == null && <span className="text-muted-foreground/40">bin</span>}
        </span>
        <button
          type="button"
          title="Revert file"
          className="hidden text-muted-foreground/50 transition hover:text-destructive group-hover:block"
          onClick={(e) => { e.stopPropagation(); setConfirmRevert(true); }}
        >
          <RotateCcw className="h-3 w-3" />
        </button>
      </div>
      {expanded && (
        loadingDiff ? (
          <div className="flex items-center justify-center py-3"><Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" /></div>
        ) : diff !== null ? (
          <DiffView diff={diff} />
        ) : null
      )}
      <ConfirmDialog
        open={confirmRevert}
        title="Revert changes?"
        body={<span>Discard all uncommitted changes to <span className="font-mono-ui text-foreground">{file.path}</span>.</span>}
        confirmLabel="Revert"
        destructive
        onConfirm={() => void revert()}
        onCancel={() => {}}
        onClose={() => setConfirmRevert(false)}
      />
    </div>
  );
}

const GROUPS: { key: WorkspaceGitFile["status"]; label: string }[] = [
  { key: "modified", label: "Edited" },
  { key: "added", label: "Added" },
  { key: "deleted", label: "Deleted" },
];

export function WorkspaceChangesPanel({ slug }: { slug: string }) {
  const [status, setStatus] = useState<WorkspaceGitStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const reloadTimerRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setStatus(await api.getWorkspaceGitStatus(slug));
    } catch (e) {
      console.error("Git status failed", e);
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => { void load(); }, [load]);

  // Refresh on the same signals the Files pane uses.
  useEventBus((env: SparkEventEnvelope) => {
    if (env.topic !== "chat.turn_done" && env.topic !== "workspace.files.changed") return;
    if (reloadTimerRef.current !== null) window.clearTimeout(reloadTimerRef.current);
    reloadTimerRef.current = window.setTimeout(() => { void load(); }, 400);
  });

  useEffect(() => () => {
    if (reloadTimerRef.current !== null) window.clearTimeout(reloadTimerRef.current);
  }, []);

  const grouped = useMemo(() => {
    const map = new Map<WorkspaceGitFile["status"], WorkspaceGitFile[]>();
    for (const f of status?.files ?? []) {
      const arr = map.get(f.status) ?? [];
      arr.push(f);
      map.set(f.status, arr);
    }
    return map;
  }, [status]);

  const commitPrompt = () => {
    window.dispatchEvent(new CustomEvent("spark:compose", { detail: "Commit these changes with a clear message, then push." }));
  };

  if (status && !status.is_repo) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-xs text-muted-foreground/60">
        <GitBranch className="h-6 w-6 opacity-30" />
        <p>Not a git repository.<br />Ask the agent to run <span className="font-mono-ui text-foreground/70">git init</span>.</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex h-7 shrink-0 items-center gap-1.5 border-b border-border px-2">
        <GitBranch className="h-3 w-3 shrink-0 text-muted-foreground/60" />
        <span className="min-w-0 flex-1 truncate font-mono-ui text-[11px] text-muted-foreground">{status?.branch ?? "—"}</span>
        {status && (status.total_adds > 0 || status.total_dels > 0) && (
          <span className="shrink-0 font-mono-ui text-[10px]">
            <span className="text-emerald-400/80">+{status.total_adds}</span>{" "}
            <span className="text-red-400/80">-{status.total_dels}</span>
          </span>
        )}
        <button type="button" title="Refresh" onClick={() => void load()} className="rounded p-0.5 text-muted-foreground/60 hover:text-foreground">
          <Loader2 className={cn("h-3.5 w-3.5", loading ? "animate-spin" : "hidden")} />
          {!loading && <RotateCcw className="h-3.5 w-3.5" />}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {status && status.files.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-xs text-muted-foreground/50">
            <Check2 />
            <p>No changes.<br />Working tree is clean.</p>
          </div>
        ) : (
          GROUPS.map(({ key, label }) => {
            const files = grouped.get(key) ?? [];
            if (!files.length) return null;
            return (
              <div key={key}>
                <div className="sticky top-0 z-10 bg-background/90 px-2 py-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50 backdrop-blur">
                  {label} · {files.length}
                </div>
                {files.map((f) => (
                  <ChangeRow key={f.path} slug={slug} file={f} onReverted={() => void load()} />
                ))}
              </div>
            );
          })
        )}
      </div>

      {/* Footer: hand off to the agent */}
      {status?.is_repo && status.files.length > 0 && (
        <div className="shrink-0 border-t border-border p-2">
          <Button size="sm" className="h-7 w-full gap-1.5 text-xs" onClick={commitPrompt}>
            <GitBranch className="h-3.5 w-3.5" />
            Commit or push…
          </Button>
        </div>
      )}
    </div>
  );
}

function Check2() {
  return (
    <svg viewBox="0 0 24 24" className="h-6 w-6 opacity-30" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}
