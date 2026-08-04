import { FileCode2, FolderOpen, GitBranch, Minus, Plus } from "lucide-react";
import type { WebChangedFile, WebChangedFiles } from "@/lib/api";

export interface ChangedFilesCardProps {
  changedFiles: WebChangedFiles | null | undefined;
  onOpenFile?: (path: string) => void;
}

function countFor(file: WebChangedFile, key: "adds" | "dels", fallbackKey: "additions" | "deletions"): number | null {
  const direct = file[fallbackKey];
  if (typeof direct === "number") return direct;
  const snapshot = file.after ?? file.before;
  const value = snapshot?.[key];
  return typeof value === "number" ? value : null;
}

function ChangeCount({ value, kind }: { value: number | null; kind: "additions" | "deletions" }) {
  const Icon = kind === "additions" ? Plus : Minus;
  return (
    <span className={kind === "additions" ? "text-success" : "text-destructive"} aria-label={`${value ?? 0} ${kind}`}>
      <Icon className="mr-0.5 inline h-3 w-3" aria-hidden="true" />{value ?? "—"}
    </span>
  );
}

export function ChangedFilesCard({ changedFiles, onOpenFile }: ChangedFilesCardProps) {
  if (!changedFiles || changedFiles.files.length === 0) return null;

  return (
    <section
      aria-label="Files changed in this turn"
      data-testid="changed-files-card"
      className="rounded-xl border border-primary/20 bg-primary/[0.045] p-3 text-xs"
    >
      <div className="flex items-center gap-2">
        <FileCode2 className="h-4 w-4 text-primary" aria-hidden="true" />
        <h3 className="font-medium text-foreground">Files changed</h3>
        <span className="text-muted-foreground">{changedFiles.count || changedFiles.files.length}</span>
        {changedFiles.branch && (
          <span className="ml-auto inline-flex max-w-[45%] items-center gap-1 truncate text-muted-foreground" title={changedFiles.branch}>
            <GitBranch className="h-3 w-3 shrink-0" aria-hidden="true" />
            <span className="truncate">{changedFiles.branch}</span>
          </span>
        )}
      </div>
      <ul className="mt-2 space-y-1.5" aria-label="Changed files">
        {changedFiles.files.map((file) => {
          const content = (
            <>
              <FileCode2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate text-left font-mono text-[11px]" title={file.path}>{file.path}</span>
              <span className="flex shrink-0 gap-2 tabular-nums" aria-label={`${file.path} changes`}>
                <ChangeCount value={countFor(file, "adds", "additions")} kind="additions" />
                <ChangeCount value={countFor(file, "dels", "deletions")} kind="deletions" />
              </span>
            </>
          );
          return (
            <li key={file.path}>
              {onOpenFile ? (
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-muted-foreground transition hover:bg-foreground/[0.06] hover:text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  aria-label={`Open ${file.path}`}
                  onClick={() => onOpenFile(file.path)}
                >
                  {content}
                </button>
              ) : (
                <div className="flex items-center gap-2 px-1.5 py-1 text-muted-foreground">{content}</div>
              )}
            </li>
          );
        })}
      </ul>
      {onOpenFile && (
        <p className="mt-2 flex items-center gap-1 text-[10px] text-muted-foreground/70">
          <FolderOpen className="h-3 w-3" aria-hidden="true" /> Select a file to open it.
        </p>
      )}
    </section>
  );
}
