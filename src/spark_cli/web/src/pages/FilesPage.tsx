import { lazy, useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Eye,
  File,
  FileText,
  Folder,
  FolderOpen,
  GripVertical,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api, mediaFileUrl } from "@/lib/api";
import type { FileListEntry, WorkspaceProject } from "@/lib/api";
import {
  GLOBAL_NAV_EVENT,
  setGlobalNavTarget,
  takeGlobalNavTarget,
  type GlobalNavTarget,
} from "@/lib/globalNavigation";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LazyLoadBoundary } from "@/components/LazyLoadBoundary";
import { useSessionStore } from "@/lib/sessionStore";
import { ROOT_PATH, fileEntryFromPath, parentDirForFile } from "./filesPathUtils";

const CodeEditor = lazy(() => import("@/components/files/CodeEditor"));

// ── File utilities ─────────────────────────────────────────────────────────────

const TEXT_EXTS = new Set([
  "ts", "tsx", "js", "jsx", "py", "md", "txt", "yaml", "yml",
  "json", "html", "css", "sh", "toml", "env", "ini", "cfg", "xml",
  "csv", "log", "sql", "rs", "go", "java", "c", "cpp", "h",
]);

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "bmp"]);
const VIDEO_EXTS = new Set(["mp4", "webm", "ogg", "mov"]);

function extOf(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

type FileCategory = "text" | "image" | "video" | "binary";

function fileCategory(name: string): FileCategory {
  const ext = extOf(name);
  if (IMAGE_EXTS.has(ext)) return "image";
  if (VIDEO_EXTS.has(ext)) return "video";
  if (TEXT_EXTS.has(ext)) return "text";
  return "binary";
}

function languageFor(name: string): string {
  const ext = extOf(name);
  const map: Record<string, string> = {
    bash: "bash", css: "css", env: "ini", html: "xml", ini: "ini",
    js: "javascript", jsx: "javascript", json: "json", md: "markdown",
    py: "python", sh: "bash", ts: "typescript", tsx: "typescript",
    toml: "ini", txt: "plaintext", xml: "xml", yaml: "yaml", yml: "yaml",
    sql: "sql", rs: "rust", go: "go",
  };
  return map[ext] ?? "plaintext";
}

function FileIcon({ name, isDir = false }: { name: string; isDir?: boolean }) {
  if (isDir) return <Folder className="h-4 w-4 shrink-0 text-amber-300/80" />;
  const ext = extOf(name);
  if (TEXT_EXTS.has(ext)) return <FileText className="h-4 w-4 shrink-0 text-sky-300/70" />;
  if (IMAGE_EXTS.has(ext)) return <File className="h-4 w-4 shrink-0 text-purple-300/70" />;
  return <File className="h-4 w-4 shrink-0 text-muted-foreground/60" />;
}

// ── Breadcrumb ─────────────────────────────────────────────────────────────────

function Breadcrumb({ path, onNavigate }: { path: string; onNavigate: (p: string) => void }) {
  // path "." → root only; "projects/wiki" → ["projects", "wiki"]
  const isRoot = path === ROOT_PATH;
  const parts = isRoot ? [] : path.split("/").filter(Boolean);
  return (
    <div className="flex items-center gap-0.5 overflow-x-auto text-xs text-muted-foreground scrollbar-none">
      <button
        type="button"
        className={cn("shrink-0 hover:text-foreground transition", isRoot && "text-foreground font-medium")}
        onClick={() => onNavigate(ROOT_PATH)}
      >
        Workspace
      </button>
      {parts.map((part, i) => {
        const segPath = parts.slice(0, i + 1).join("/");
        const isLast = i === parts.length - 1;
        return (
          <span key={segPath} className="flex items-center gap-0.5 shrink-0">
            <ChevronRight className="h-3 w-3 opacity-40" />
            <button
              type="button"
              className={cn("hover:text-foreground transition", isLast && "text-foreground font-medium")}
              onClick={() => !isLast && onNavigate(segPath)}
            >
              {part}
            </button>
          </span>
        );
      })}
    </div>
  );
}

// ── Resize divider ─────────────────────────────────────────────────────────────

function ResizeDivider({ onDrag }: { onDrag: (delta: number) => void }) {
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    let lastX = e.clientX;
    const onMove = (mv: MouseEvent) => { const d = mv.clientX - lastX; lastX = mv.clientX; onDrag(d); };
    const onUp = () => { document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };
  return (
    <div onMouseDown={handleMouseDown} className="group relative flex w-2 shrink-0 cursor-col-resize items-center justify-center">
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border transition-colors group-hover:bg-primary/50 group-active:bg-primary/70" />
      <GripVertical className="relative z-10 h-4 w-4 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/50 group-active:text-primary/70" />
    </div>
  );
}

// ── File editor / viewer ───────────────────────────────────────────────────────

type OpenFile = {
  path: string;
  name: string;
  content: string | null;
  loading: boolean;
  dirty: boolean;
};

function MediaViewer({ file }: { file: OpenFile }) {
  const cat = fileCategory(file.name);
  const url = mediaFileUrl(file.path);
  if (cat === "image") {
    return (
      <div className="flex h-full flex-col items-center gap-4 overflow-auto p-6">
        <img src={url} alt={file.name} className="max-w-full rounded border border-border object-contain shadow" />
        <a href={url} download={file.name} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
          <Download className="h-3.5 w-3.5" /> Download {file.name}
        </a>
      </div>
    );
  }
  if (cat === "video") {
    return (
      <div className="flex h-full flex-col items-center gap-4 overflow-auto p-6">
        <video src={url} controls className="max-w-full rounded border border-border shadow" />
        <a href={url} download={file.name} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
          <Download className="h-3.5 w-3.5" /> Download {file.name}
        </a>
      </div>
    );
  }
  const url2 = mediaFileUrl(file.path);
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center p-8">
      <File className="h-12 w-12 text-muted-foreground/20" />
      <p className="text-sm font-medium text-foreground">{file.name}</p>
      <p className="text-xs text-muted-foreground/60">Binary file — no preview available.</p>
      <a href={url2} download={file.name} className="flex items-center gap-1.5 text-xs text-primary hover:underline">
        <Download className="h-3.5 w-3.5" /> Download
      </a>
    </div>
  );
}

// ── File browser panel ─────────────────────────────────────────────────────────

function FileBrowser({
  currentPath,
  selectedFile,
  onNavigate,
  onSelectFile,
  onRefresh,
  projects,
  onRenameProject,
  onDeleteProject,
}: {
  currentPath: string;
  selectedFile: string | null;
  onNavigate: (path: string) => void;
  onSelectFile: (entry: FileListEntry) => void;
  onRefresh: () => void;
  projects: WorkspaceProject[];
  onRenameProject: (slug: string, name: string) => Promise<string>;
  onDeleteProject: (slug: string) => Promise<void>;
}) {
  const [entries, setEntries] = useState<FileListEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [confirmProjectDelete, setConfirmProjectDelete] = useState<WorkspaceProject | null>(null);
  const [renamingProject, setRenamingProject] = useState<WorkspaceProject | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [projectActionPending, setProjectActionPending] = useState(false);
  const [projectActionError, setProjectActionError] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listChatFiles(currentPath, showHidden);
      setEntries(res.entries);
    } catch (e) {
      console.error("Failed to list files", e);
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [currentPath, showHidden]);

  useEffect(() => {
    setSearchQ("");
    void load();
  }, [load]);

  const handleUpload = async (files: FileList | File[]) => {
    const arr = Array.from(files);
    if (!arr.length) return;
    setUploading(true);
    try {
      await api.uploadChatFiles(arr);
      await load();
      onRefresh();
    } catch (e) {
      console.error("Upload failed", e);
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (path: string) => {
    try {
      await api.deleteChatFile(path);
      setConfirmDelete(null);
      await load();
      onRefresh();
    } catch (e) {
      console.error("Delete failed", e);
    }
  };

  const projectForEntry = (entry: FileListEntry) => (
    currentPath === ROOT_PATH
      ? projects.find((project) => project.slug === entry.name || project.name === entry.name) ?? null
      : null
  );

  const commitProjectRename = async () => {
    const project = renamingProject;
    const nextName = renameValue.trim();
    if (!project) return;
    if (!nextName || nextName === project.name) {
      setRenamingProject(null);
      setRenameValue("");
      return;
    }
    setProjectActionPending(true);
    setProjectActionError(null);
    try {
      await onRenameProject(project.slug, nextName);
      setRenamingProject(null);
      setRenameValue("");
      await load();
      onRefresh();
    } catch (error) {
      setProjectActionError(error instanceof Error ? error.message : "Could not rename project");
    } finally {
      setProjectActionPending(false);
    }
  };

  const deleteConfirmedProject = async () => {
    const project = confirmProjectDelete;
    if (!project) return;
    setProjectActionPending(true);
    setProjectActionError(null);
    try {
      await onDeleteProject(project.slug);
      setConfirmProjectDelete(null);
      await load();
      onRefresh();
    } catch (error) {
      setProjectActionError(error instanceof Error ? error.message : "Could not delete project");
    } finally {
      setProjectActionPending(false);
    }
  };

  const canGoUp = currentPath !== ROOT_PATH;
  const visible = searchQ.trim()
    ? entries.filter((e) => e.name.toLowerCase().includes(searchQ.toLowerCase()))
    : entries;
  const FILE_LIST_CAP = 500;
  const allDirs = visible.filter((e) => e.type === "dir");
  const allFiles = visible.filter((e) => e.type !== "dir");
  const dirs = allDirs.slice(0, FILE_LIST_CAP);
  const files = allFiles.slice(0, FILE_LIST_CAP - dirs.length);
  const cappedTotal = allDirs.length + allFiles.length;
  const shown = dirs.length + files.length;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="shrink-0 border-b border-border bg-card/50 px-3 py-2">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            {canGoUp && (
              <button
                type="button"
                title="Go up"
                onClick={() => {
                  const parts = currentPath.split("/").slice(0, -1);
                  onNavigate(parts.length === 0 ? ROOT_PATH : parts.join("/"));
                }}
                className="grid h-6 w-6 place-items-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground transition"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
            )}
            <Breadcrumb path={currentPath} onNavigate={onNavigate} />
          </div>
          <div className="flex items-center gap-1 shrink-0">
            {uploading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
            <button
              type="button"
              title="Upload files"
              onClick={() => fileInputRef.current?.click()}
              className="grid h-7 w-7 place-items-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground transition"
            >
              <Plus className="h-4 w-4" />
            </button>
            <button
              type="button"
              title={showHidden ? "Hide hidden files" : "Show hidden files"}
              aria-pressed={showHidden}
              onClick={() => setShowHidden((v) => !v)}
              className={cn(
                "grid h-7 w-7 place-items-center rounded text-muted-foreground transition hover:bg-secondary hover:text-foreground",
                showHidden && "bg-secondary text-foreground",
              )}
            >
              <Eye className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              title="Refresh"
              onClick={() => void load()}
              className="grid h-7 w-7 place-items-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground transition"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
            </button>
          </div>
          <input ref={fileInputRef} type="file" multiple className="hidden" onChange={(e) => e.target.files && void handleUpload(e.target.files)} />
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/60" />
          <Input
            className="h-7 pl-8 text-xs"
            placeholder="Filter files…"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
          />
          {searchQ && (
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setSearchQ("")}
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* File list */}
      <div
        className={cn(
          "min-h-0 flex-1 overflow-y-auto transition-all",
          dragOver && "bg-primary/5 ring-2 ring-inset ring-primary/20",
        )}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragOver(false); }}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files.length) void handleUpload(e.dataTransfer.files); }}
      >
        {loading && !entries.length && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {!loading && entries.length === 0 && (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <Upload className="h-8 w-8 text-muted-foreground/25" />
            <p className="text-sm font-medium text-muted-foreground">No files yet</p>
            <p className="text-xs text-muted-foreground/60">
              Drop files here or click <strong>+</strong> to upload.
            </p>
          </div>
        )}

        {/* Confirm delete dialog */}
        {confirmDelete && (
          <div className="mx-3 mt-3 rounded-sm border border-destructive/40 bg-background p-3">
            <p className="text-xs font-medium text-foreground mb-1">
              Delete <span className="font-mono text-destructive">{confirmDelete.split("/").pop()}</span>?
            </p>
            <p className="text-[11px] text-muted-foreground mb-2">This cannot be undone.</p>
            <div className="flex gap-2">
              <Button size="sm" variant="destructive" className="h-6 flex-1 text-xs" onClick={() => void handleDelete(confirmDelete)}>
                Delete
              </Button>
              <Button size="sm" variant="ghost" className="h-6 px-2" onClick={() => setConfirmDelete(null)}>
                <X className="h-3 w-3" />
              </Button>
            </div>
          </div>
        )}

        {confirmProjectDelete && (
          <div className="mx-3 mt-3 rounded-md border border-destructive/40 bg-background p-3" role="alertdialog" aria-label="Confirm project deletion">
            <p className="mb-1 text-xs font-medium text-foreground">
              Delete project <span className="font-semibold text-destructive">{confirmProjectDelete.name}</span>?
            </p>
            <p className="mb-2 text-[11px] leading-4 text-muted-foreground">
              This permanently removes the project folder and all files inside it. This cannot be undone.
            </p>
            <div className="flex gap-2">
              <Button size="sm" variant="destructive" disabled={projectActionPending} className="h-7 flex-1 text-xs" onClick={() => void deleteConfirmedProject()}>
                {projectActionPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                Delete project
              </Button>
              <Button size="sm" variant="ghost" disabled={projectActionPending} className="h-7 px-2" onClick={() => setConfirmProjectDelete(null)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {projectActionError && (
          <p className="mx-3 mt-2 rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-[11px] text-destructive">
            {projectActionError}
          </p>
        )}

        {/* Directories */}
        {dirs.map((entry) => {
          const project = projectForEntry(entry);
          const isRenaming = project !== null && renamingProject?.slug === project.slug;
          return (
            <div
              key={entry.path}
              className="spark-list-row group flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-muted-foreground transition hover:bg-secondary hover:text-foreground select-none"
              onClick={() => !isRenaming && onNavigate(entry.path)}
            >
              <FolderOpen className="h-4 w-4 shrink-0 text-amber-300/80" />
              {isRenaming ? (
                <form
                  className="flex min-w-0 flex-1 items-center gap-1.5"
                  onSubmit={(event) => { event.preventDefault(); void commitProjectRename(); }}
                  onClick={(event) => event.stopPropagation()}
                >
                  <Input
                    autoFocus
                    value={renameValue}
                    disabled={projectActionPending}
                    aria-label="Project name"
                    className="h-7 min-w-0 flex-1 px-2 text-xs"
                    onChange={(event) => setRenameValue(event.target.value)}
                    onFocus={(event) => event.currentTarget.select()}
                    onKeyDown={(event) => {
                      if (event.key === "Escape") {
                        event.preventDefault();
                        setRenamingProject(null);
                        setRenameValue("");
                      }
                    }}
                  />
                  {projectActionPending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                </form>
              ) : (
                <span className="flex-1 truncate">{project?.name ?? entry.name}</span>
              )}
              {project && !isRenaming ? (
                <div className="ml-1 hidden shrink-0 items-center gap-1 group-hover:flex group-focus-within:flex">
                  <button
                    type="button"
                    title="Rename project"
                    aria-label={`Rename ${project.name}`}
                    className="rounded p-0.5 text-muted-foreground/50 hover:bg-background/70 hover:text-foreground"
                    onClick={(event) => {
                      event.stopPropagation();
                      setProjectActionError(null);
                      setRenameValue(project.name);
                      setRenamingProject(project);
                    }}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    title="Delete project"
                    aria-label={`Delete ${project.name}`}
                    className="rounded p-0.5 text-muted-foreground/50 hover:bg-destructive/10 hover:text-destructive"
                    onClick={(event) => {
                      event.stopPropagation();
                      setProjectActionError(null);
                      setConfirmProjectDelete(project);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : !isRenaming ? (
                <ChevronRight className="h-3.5 w-3.5 opacity-30 group-hover:opacity-60" />
              ) : null}
            </div>
          );
        })}

        {/* Files */}
        {files.map((entry) => (
          <div
            key={entry.path}
            className={cn(
              "spark-list-row group flex cursor-pointer items-center gap-2 px-3 py-2 text-sm transition select-none",
              selectedFile === entry.path
                ? "bg-primary/15 text-foreground"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
            onClick={() => onSelectFile(entry)}
          >
            <FileIcon name={entry.name} />
            <span className="flex-1 truncate">{entry.name}</span>
            <div className="ml-1 hidden shrink-0 items-center gap-1.5 group-hover:flex">
              <a
                href={mediaFileUrl(entry.path)}
                download={entry.name}
                onClick={(e) => e.stopPropagation()}
                title="Download"
                className="text-muted-foreground/40 hover:text-foreground"
              >
                <Download className="h-3.5 w-3.5" />
              </a>
              <button
                type="button"
                title="Delete"
                className="text-muted-foreground/40 hover:text-destructive"
                onClick={(e) => { e.stopPropagation(); setConfirmDelete(entry.path); }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        ))}

        {!loading && visible.length === 0 && entries.length > 0 && (
          <div className="py-8 text-center text-xs text-muted-foreground/60">No matches</div>
        )}

        {shown < cappedTotal && (
          <div className="px-3 py-2 text-[11px] text-muted-foreground/50">
            Showing {shown} of {cappedTotal} items — refine your search to see more
          </div>
        )}

        {/* Drop overlay hint */}
        {dragOver && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div className="rounded-sm border-2 border-dashed border-primary/40 bg-primary/5 px-6 py-4 text-sm text-primary">
              Drop to upload
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function FilesPage() {
  const { projects, renameProject, deleteProject } = useSessionStore();
  const [currentPath, setCurrentPath] = useState(ROOT_PATH);
  const [selectedFile, setSelectedFile] = useState<OpenFile | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [saving, setSaving] = useState(false);
  const [browserWidth, setBrowserWidth] = useState(() => {
    const saved = localStorage.getItem("spark-files-browser-width");
    return saved ? Math.max(220, parseInt(saved, 10)) : 320;
  });

  const handleDrag = useCallback((delta: number) => {
    setBrowserWidth((w) => {
      const next = Math.max(220, Math.min(600, w + delta));
      localStorage.setItem("spark-files-browser-width", String(next));
      return next;
    });
  }, []);

  const handleSelectFile = useCallback(async (entry: FileListEntry) => {
    // Canvas files open in the Canvas tab rather than the inline editor.
    if (entry.name.endsWith(".canvas.json")) {
      const id = entry.name.slice(0, -".canvas.json".length);
      setGlobalNavTarget({ type: "canvas", id, scope: "global", slug: null });
      return;
    }
    const cat = fileCategory(entry.name);
    if (cat === "text") {
      setSelectedFile({ path: entry.path, name: entry.name, content: null, loading: true, dirty: false });
      try {
        const content = await api.readChatFile(entry.path);
        setSelectedFile({ path: entry.path, name: entry.name, content, loading: false, dirty: false });
      } catch (e) {
        setSelectedFile({ path: entry.path, name: entry.name, content: `Error loading file: ${e}`, loading: false, dirty: false });
      }
    } else {
      setSelectedFile({ path: entry.path, name: entry.name, content: null, loading: false, dirty: false });
    }
  }, []);

  const handleNavigate = (path: string) => {
    setCurrentPath(path);
    setSelectedFile(null);
  };

  const handleContentChange = useCallback((content: string) => {
    setSelectedFile((f) => f ? { ...f, content, dirty: true } : f);
  }, []);

  const handleSave = useCallback(async () => {
    if (!selectedFile || !selectedFile.dirty || selectedFile.content === null) return;
    setSaving(true);
    try {
      await api.writeChatFile(selectedFile.path, selectedFile.content);
      setSelectedFile((f) => f ? { ...f, dirty: false } : f);
    } catch (e) {
      console.error("Save failed", e);
    } finally {
      setSaving(false);
    }
  }, [selectedFile]);

  const openFileTarget = useCallback((target: Extract<GlobalNavTarget, { type: "file" }>) => {
    const entry = fileEntryFromPath(target.path, target.name);
    setCurrentPath(parentDirForFile(target.path));
    void handleSelectFile(entry);
  }, [handleSelectFile]);

  useEffect(() => {
    const initial = takeGlobalNavTarget("file");
    if (initial?.type === "file") openFileTarget(initial);

    const handler = (event: Event) => {
      const target = (event as CustomEvent<GlobalNavTarget>).detail;
      if (target?.type === "file") openFileTarget(target);
    };
    window.addEventListener(GLOBAL_NAV_EVENT, handler);
    return () => window.removeEventListener(GLOBAL_NAV_EVENT, handler);
  }, [openFileTarget]);

  const cat = selectedFile ? fileCategory(selectedFile.name) : null;
  const isText = cat === "text";

  return (
    <div className="flex h-full min-h-0 overflow-hidden border-t border-border bg-card/70 backdrop-blur-xl">
      {/* Left: file browser */}
      <div
        className="relative flex min-h-0 shrink-0 flex-col overflow-hidden border-r border-border bg-card/40"
        style={{ width: browserWidth }}
      >
        <FileBrowser
          currentPath={currentPath}
          selectedFile={selectedFile?.path ?? null}
          onNavigate={handleNavigate}
          onSelectFile={handleSelectFile}
          onRefresh={() => setRefreshKey((k) => k + 1)}
          projects={projects}
          onRenameProject={renameProject}
          onDeleteProject={deleteProject}
          key={refreshKey}
        />
      </div>

      <ResizeDivider onDrag={handleDrag} />

      {/* Right: editor / viewer */}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {selectedFile ? (
          <>
            {/* Panel header */}
            <div className="flex h-9 shrink-0 items-center justify-between border-b border-border bg-card/50 px-3">
              <div className="flex items-center gap-2 min-w-0">
                <FileIcon name={selectedFile.name} />
                <span className="truncate text-sm font-medium text-foreground">{selectedFile.name}</span>
                {selectedFile.dirty && (
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" title="Unsaved changes" />
                )}
              </div>
              <div className="flex items-center gap-1 shrink-0 ml-2">
                {isText && selectedFile.dirty && (
                  <button
                    type="button"
                    title="Save (⌘S)"
                    onClick={() => void handleSave()}
                    disabled={saving}
                    className="flex items-center gap-1 rounded px-2 h-6 text-[11px] text-muted-foreground hover:bg-secondary hover:text-foreground transition disabled:opacity-50"
                  >
                    {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
                    Save
                  </button>
                )}
                <button
                  type="button"
                  className="grid h-6 w-6 shrink-0 place-items-center rounded text-muted-foreground hover:bg-secondary hover:text-foreground transition"
                  onClick={() => setSelectedFile(null)}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* Content area */}
            <div className="min-h-0 flex-1 overflow-hidden">
              {selectedFile.loading ? (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                </div>
              ) : isText ? (
                <div className="flex h-full flex-col overflow-hidden">
                  {/* Language badge strip */}
                  <div className="flex h-7 shrink-0 items-center justify-between border-b border-border bg-background/40 px-3 text-[10px] text-muted-foreground">
                    <span className="truncate font-mono-ui opacity-60">{selectedFile.path}</span>
                    <span className="uppercase tracking-[0.12em] shrink-0 ml-2">{languageFor(selectedFile.name)}</span>
                  </div>
                  <div className="min-h-0 flex-1 overflow-auto">
                    <LazyLoadBoundary label="editor">
                      <CodeEditor
                        filename={selectedFile.name}
                        value={selectedFile.content ?? ""}
                        onChange={handleContentChange}
                        onSave={handleSave}
                      />
                    </LazyLoadBoundary>
                  </div>
                </div>
              ) : (
                <MediaViewer file={selectedFile} />
              )}
            </div>
          </>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center text-muted-foreground">
            <FolderOpen className="h-12 w-12 opacity-20" />
            <p className="text-sm font-medium text-foreground">Select a file to open</p>
            <p className="text-xs opacity-60">Text files open as an editor; images and videos are previewed.</p>
          </div>
        )}
      </div>
    </div>
  );
}
