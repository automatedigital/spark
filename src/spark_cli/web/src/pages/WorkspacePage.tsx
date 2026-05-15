import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  File,
  FileText,
  Film,
  Folder,
  FolderOpen,
  GripVertical,
  Image,
  Loader2,
  MessageSquare,
  Plus,
  Send,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api, workspaceRawFileUrl } from "@/lib/api";
import type {
  SessionInfo,
  WorkspaceFileNode,
  WorkspaceProject,
} from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatPanel } from "@/components/ChatPanel";
import { useEventBus } from "@/hooks/useEventBus";
import type { SparkEventEnvelope } from "@/hooks/useEventBus";

// ── Types ─────────────────────────────────────────────────────────────────────

type FileTab = {
  id: string;        // = file path
  path: string;
  label: string;     // filename only
  mime: string;
  content: string | null;  // null for binary or not-yet-loaded
  loading: boolean;
};

type ActiveTab = "chat" | string;  // "chat" or a file path id

// ── localStorage persistence ──────────────────────────────────────────────────

const COL_WIDTHS_KEY = "spark-workspace-col-widths";

function loadColWidths(): [number, number] {
  try {
    const raw = localStorage.getItem(COL_WIDTHS_KEY);
    if (raw) {
      const p = JSON.parse(raw) as unknown;
      if (Array.isArray(p) && typeof p[0] === "number" && typeof p[1] === "number")
        return [Math.max(160, p[0] as number), Math.max(200, p[1] as number)];
    }
  } catch { /* ignore */ }
  return [240, 300];
}

function saveColWidths(l: number, c: number): void {
  localStorage.setItem(COL_WIDTHS_KEY, JSON.stringify([l, c]));
}

// ── File category ─────────────────────────────────────────────────────────────

function getFileCategory(mime: string, filename: string): "text" | "image" | "video" | "binary" {
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (
    mime.startsWith("text/") ||
    ["application/json", "application/yaml", "application/xml"].includes(mime)
  ) return "text";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const textExts = new Set([
    "ts", "tsx", "js", "jsx", "py", "md", "txt", "yaml", "yml",
    "json", "html", "css", "sh", "toml", "env", "ini", "cfg",
  ]);
  return textExts.has(ext) ? "text" : "binary";
}

// ── File tree node ────────────────────────────────────────────────────────────

function FileNodeRow({
  node,
  depth,
  onSelect,
  selectedPath,
  onDelete,
}: {
  node: WorkspaceFileNode;
  depth: number;
  onSelect: (node: WorkspaceFileNode) => void;
  selectedPath: string | null;
  onDelete: (node: WorkspaceFileNode) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isDir = node.type === "dir";
  const isSelected = node.path === selectedPath;

  return (
    <div>
      <div
        className={cn(
          "group flex items-center gap-1.5 rounded-sm px-2 py-1 text-xs cursor-pointer select-none transition",
          isSelected && !isDir
            ? "bg-primary/20 text-foreground"
            : "text-muted-foreground hover:bg-secondary hover:text-foreground",
        )}
        style={{ paddingLeft: `${8 + depth * 12}px` }}
        onClick={() => {
          if (isDir) {
            setExpanded((v) => !v);
          } else {
            onSelect(node);
          }
        }}
      >
        {isDir ? (
          <>
            <span className="text-muted-foreground/60">
              {expanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
            </span>
            {expanded ? (
              <FolderOpen className="h-3.5 w-3.5 text-amber-300/80 shrink-0" />
            ) : (
              <Folder className="h-3.5 w-3.5 text-amber-300/80 shrink-0" />
            )}
          </>
        ) : (
          <>
            <span className="w-3 shrink-0" />
            <FileIcon name={node.name} />
          </>
        )}
        <span className="flex-1 truncate">{node.name}</span>
        {!isDir && (
          <button
            type="button"
            className="hidden group-hover:block ml-1 text-muted-foreground/50 hover:text-destructive"
            onClick={(e) => {
              e.stopPropagation();
              onDelete(node);
            }}
          >
            <Trash2 className="h-3 w-3" />
          </button>
        )}
      </div>
      {isDir && expanded && node.children && (
        <div>
          {node.children.map((child) => (
            <FileNodeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelect={onSelect}
              selectedPath={selectedPath}
              onDelete={onDelete}
            />
          ))}
          {node.children.length === 0 && (
            <div
              className="px-2 py-0.5 text-xs text-muted-foreground/40 italic"
              style={{ paddingLeft: `${8 + (depth + 1) * 12}px` }}
            >
              empty
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FileIcon({ name }: { name: string }) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const textExts = new Set([
    "ts", "tsx", "js", "jsx", "py", "md", "txt", "yaml", "yml", "json",
    "html", "css", "sh", "toml", "env", "ini", "cfg",
  ]);
  return textExts.has(ext) ? (
    <FileText className="h-3.5 w-3.5 text-sky-300/70 shrink-0" />
  ) : (
    <File className="h-3.5 w-3.5 text-muted-foreground/60 shrink-0" />
  );
}

// ── Resize divider ────────────────────────────────────────────────────────────

function ResizeDivider({ onDrag }: { onDrag: (delta: number) => void }) {
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    let lastX = e.clientX;
    const onMove = (mv: MouseEvent) => {
      const delta = mv.clientX - lastX;
      lastX = mv.clientX;
      onDrag(delta);
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  return (
    <div
      onMouseDown={handleMouseDown}
      className="group relative flex w-3 shrink-0 cursor-col-resize items-center justify-center"
    >
      {/* visible 1px rule */}
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border transition-colors group-hover:bg-primary/50 group-active:bg-primary/70" />
      {/* grip handle — appears on hover */}
      <GripVertical className="relative z-10 h-4 w-4 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/50 group-active:text-primary/70" />
    </div>
  );
}

// ── Projects sidebar ──────────────────────────────────────────────────────────

function ProjectsSidebar({
  projects,
  activeSlug,
  onSelect,
  onCreate,
  loading,
}: {
  projects: WorkspaceProject[];
  activeSlug: string | null;
  onSelect: (slug: string) => void;
  onCreate: (name: string) => Promise<void>;
  loading: boolean;
}) {
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);

  const handleCreate = async () => {
    const name = newName.trim();
    if (!name) return;
    setSaving(true);
    try {
      await onCreate(name);
      setNewName("");
      setCreating(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex h-full flex-col border-r border-border bg-card/60">
      <div className="flex items-center justify-between border-b border-border px-3 py-3">
        <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Projects
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-6 w-6 p-0"
          title="New project"
          onClick={() => setCreating(true)}
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto py-2">
        {loading && projects.length === 0 && (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        )}
        {!loading && projects.length === 0 && !creating && (
          <p className="px-3 py-4 text-xs text-muted-foreground/60 text-center">
            No projects yet.
            <br />
            Create one to get started.
          </p>
        )}
        {projects.map((p) => (
          <button
            key={p.slug}
            type="button"
            onClick={() => onSelect(p.slug)}
            className={cn(
              "w-full text-left px-3 py-2 text-sm transition",
              activeSlug === p.slug
                ? "bg-primary/15 text-foreground border-r-2 border-primary"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            <div className="flex items-center gap-2">
              <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-300/70" />
              <span className="truncate font-medium">{p.name}</span>
            </div>
            <div className="mt-0.5 pl-5.5 text-xs text-muted-foreground/50">
              {p.file_count} {p.file_count === 1 ? "file" : "files"}
            </div>
          </button>
        ))}

        {creating && (
          <div className="mx-2 mt-2 flex flex-col gap-1.5 rounded-sm border border-border bg-background p-2">
            <Input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Project name"
              className="h-7 text-xs"
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreate();
                if (e.key === "Escape") {
                  setCreating(false);
                  setNewName("");
                }
              }}
            />
            <div className="flex gap-1">
              <Button size="sm" className="h-6 flex-1 text-xs" onClick={handleCreate} disabled={saving}>
                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Create"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 w-6 p-0"
                onClick={() => {
                  setCreating(false);
                  setNewName("");
                }}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── File panel ────────────────────────────────────────────────────────────────

function FilePanel({
  slug,
  onFileOpen,
}: {
  slug: string;
  onFileOpen: (node: WorkspaceFileNode, mime: string) => void;
}) {
  const [tree, setTree] = useState<WorkspaceFileNode[]>([]);
  const [loadingTree, setLoadingTree] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadTree = useCallback(async () => {
    setLoadingTree(true);
    try {
      const res = await api.getWorkspaceFileTree(slug);
      setTree(res.tree);
    } catch (e) {
      console.error("Tree load failed", e);
    } finally {
      setLoadingTree(false);
    }
  }, [slug]);

  useEffect(() => {
    setSelectedPath(null);
    loadTree();
  }, [slug, loadTree]);

  const handleSelectFile = (node: WorkspaceFileNode) => {
    setSelectedPath(node.path);
    onFileOpen(node, node.mime ?? "application/octet-stream");
  };

  const handleDelete = async (node: WorkspaceFileNode) => {
    if (!confirm(`Delete ${node.path}?`)) return;
    try {
      await api.deleteWorkspaceFile(slug, node.path);
      if (selectedPath === node.path) setSelectedPath(null);
      loadTree();
    } catch (e) {
      console.error("Delete failed", e);
    }
  };

  const handleUpload = async (files: FileList | File[]) => {
    const arr = Array.from(files);
    if (!arr.length) return;
    setUploading(true);
    try {
      await api.uploadWorkspaceFiles(slug, arr);
      loadTree();
    } catch (e) {
      console.error("Upload failed", e);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="flex h-full flex-col border-r border-border">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border bg-card/60 px-3 py-3">
        <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Files
        </span>
        <div className="flex items-center gap-1">
          {uploading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0"
            title="Upload files"
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="h-3.5 w-3.5" />
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => e.target.files && handleUpload(e.target.files)}
          />
        </div>
      </div>

      {/* Tree */}
      <div
        className={cn(
          "flex-1 overflow-y-auto py-1 transition",
          dragOver && "bg-primary/5 ring-2 ring-inset ring-primary/20",
        )}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (e.dataTransfer.files.length) handleUpload(e.dataTransfer.files);
        }}
      >
        {loadingTree && (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        )}
        {!loadingTree && tree.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-8 text-center text-xs text-muted-foreground/60">
            <Upload className="h-6 w-6 opacity-30" />
            <p>
              No files yet.
              <br />
              Drop files here or click upload.
            </p>
          </div>
        )}
        {tree.map((node) => (
          <FileNodeRow
            key={node.path}
            node={node}
            depth={0}
            onSelect={handleSelectFile}
            selectedPath={selectedPath}
            onDelete={handleDelete}
          />
        ))}
      </div>
    </div>
  );
}

// ── File viewer ───────────────────────────────────────────────────────────────

function FileViewer({ tab, slug }: { tab: FileTab; slug: string }) {
  const cat = getFileCategory(tab.mime, tab.label);

  if (tab.loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (cat === "image") {
    const url = workspaceRawFileUrl(slug, tab.path);
    return (
      <div className="flex h-full flex-col items-center gap-3 overflow-auto p-4">
        <img
          src={url}
          alt={tab.label}
          className="max-w-full rounded border border-border object-contain"
        />
        <a
          href={url}
          download={tab.label}
          className="text-xs text-muted-foreground hover:text-foreground underline"
        >
          Download {tab.label}
        </a>
      </div>
    );
  }

  if (cat === "video") {
    const url = workspaceRawFileUrl(slug, tab.path);
    return (
      <div className="flex h-full flex-col items-center gap-3 overflow-auto p-4">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video
          src={url}
          controls
          className="max-w-full rounded border border-border"
        />
        <a
          href={url}
          download={tab.label}
          className="text-xs text-muted-foreground hover:text-foreground underline"
        >
          Download {tab.label}
        </a>
      </div>
    );
  }

  if (cat === "text" && tab.content !== null) {
    return (
      <div className="h-full overflow-auto bg-background/60">
        <pre className="px-4 py-3 text-[0.7rem] leading-relaxed text-muted-foreground font-mono whitespace-pre-wrap break-all">
          {tab.content}
        </pre>
      </div>
    );
  }

  // binary / unknown
  const url = workspaceRawFileUrl(slug, tab.path);
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <File className="h-10 w-10 text-muted-foreground/20" />
      <p className="text-xs text-muted-foreground/60">Binary file — no preview available.</p>
      <a
        href={url}
        download={tab.label}
        className="text-xs text-primary hover:underline"
      >
        Download {tab.label}
      </a>
    </div>
  );
}

// ── File tab icon ─────────────────────────────────────────────────────────────

function FileTabIcon({ mime, name }: { mime: string; name: string }) {
  const cat = getFileCategory(mime, name);
  if (cat === "image") return <Image className="h-3 w-3 text-violet-400/70 shrink-0" />;
  if (cat === "video") return <Film className="h-3 w-3 text-pink-400/70 shrink-0" />;
  return <FileText className="h-3 w-3 text-sky-300/70 shrink-0" />;
}

// ── Right panel (chat + file tabs) ────────────────────────────────────────────

function RightPanel({
  slug,
  fileTabs,
  activeTab,
  onTabClose,
  onTabSelect,
}: {
  slug: string;
  fileTabs: FileTab[];
  activeTab: ActiveTab;
  onTabClose: (id: string) => void;
  onTabSelect: (id: ActiveTab) => void;
}) {
  const [threads, setThreads] = useState<SessionInfo[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loadingThreads, setLoadingThreads] = useState(false);
  const [startMsg, setStartMsg] = useState("");
  const [startingThread, setStartingThread] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const loadThreads = useCallback(async () => {
    setLoadingThreads(true);
    try {
      const res = await api.listWorkspaceConversations(slug);
      setThreads(res.sessions as SessionInfo[]);
    } catch (e) {
      console.error("Load threads failed", e);
    } finally {
      setLoadingThreads(false);
    }
  }, [slug]);

  useEffect(() => {
    setActiveId(null);
    setThreads([]);
    loadThreads();
  }, [slug, loadThreads]);

  useEffect(() => {
    if (!loadingThreads && threads.length === 0 && !activeId) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [loadingThreads, threads.length, activeId]);

  useEventBus((env: SparkEventEnvelope) => {
    if (env.topic === "sessions.changed") {
      const src = (env.data as { session?: { source?: string } }).session?.source ?? "";
      if (src === `workspace:${slug}`) loadThreads();
    }
  });

  const handleStartThread = async () => {
    const msg = startMsg.trim();
    if (!msg) return;
    setStartingThread(true);
    try {
      const res = await api.startWorkspaceConversation(slug, msg);
      setStartMsg("");
      setActiveId(res.session_id);
      await loadThreads();
    } catch (e) {
      console.error("Start thread failed", e);
    } finally {
      setStartingThread(false);
    }
  };

  const activeThread = threads.find((t) => t.id === activeId) ?? null;

  return (
    <div className="flex h-full flex-col">
      {/* Tab bar */}
      <div className="flex items-center border-b border-border bg-card/60 overflow-x-auto shrink-0">
        {/* Chat tab — permanent */}
        <button
          type="button"
          className={cn(
            "flex items-center gap-1.5 px-3 py-2.5 text-xs shrink-0 transition border-b-2",
            activeTab === "chat"
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
          onClick={() => onTabSelect("chat")}
        >
          <MessageSquare className="h-3 w-3" />
          Chat
        </button>

        {/* File tabs */}
        {fileTabs.map((tab) => (
          <div
            key={tab.id}
            className={cn(
              "group flex items-center gap-1.5 px-3 py-2.5 text-xs shrink-0 transition border-b-2 cursor-pointer select-none",
              activeTab === tab.id
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
            onClick={() => onTabSelect(tab.id)}
          >
            <FileTabIcon mime={tab.mime} name={tab.label} />
            <span className="max-w-[120px] truncate">{tab.label}</span>
            <button
              type="button"
              className="ml-0.5 opacity-0 group-hover:opacity-60 hover:!opacity-100 hover:text-destructive transition"
              onClick={(e) => {
                e.stopPropagation();
                onTabClose(tab.id);
              }}
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </div>
        ))}
      </div>

      {/* Content area */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {activeTab !== "chat" ? (
          (() => {
            const tab = fileTabs.find((t) => t.id === activeTab);
            return tab ? <FileViewer tab={tab} slug={slug} /> : null;
          })()
        ) : (
          /* Chat content */
          <div className="flex h-full flex-col">
            {/* Chat header */}
            <div className="flex items-center justify-between border-b border-border bg-card/60 px-3 py-2">
              <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                {activeId ? "Thread" : "Threads"}
              </span>
              {activeId && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 gap-1 px-2 text-xs"
                  onClick={() => setActiveId(null)}
                >
                  <MessageSquare className="h-3 w-3" />
                  All threads
                </Button>
              )}
            </div>

            {activeId ? (
              <ChatPanel
                sessionId={activeId}
                sessionTitle={activeThread?.title ?? activeThread?.preview ?? "Thread"}
                onBack={() => setActiveId(null)}
                onSessionCreated={(id) => setActiveId(id)}
                onSessionUpdated={() => loadThreads()}
                className="min-h-0 flex-1"
              />
            ) : (
              <div className="flex flex-1 flex-col overflow-hidden">
                {/* Thread list — hidden when empty */}
                {(loadingThreads || threads.length > 0) && (
                  <div className="flex-1 overflow-y-auto">
                    {loadingThreads && threads.length === 0 && (
                      <div className="flex items-center justify-center py-8">
                        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                      </div>
                    )}
                    {threads.map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => setActiveId(t.id)}
                        className="w-full border-b border-border/50 px-3 py-2.5 text-left transition hover:bg-secondary"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <p className="truncate text-xs font-medium text-foreground">
                            {t.title?.trim() || t.preview?.trim() || "Untitled thread"}
                          </p>
                          {t.is_active && (
                            <span className="mt-0.5 shrink-0 h-1.5 w-1.5 rounded-full bg-success" />
                          )}
                        </div>
                        <div className="mt-0.5 flex items-center gap-2 text-[0.65rem] text-muted-foreground/60">
                          <span>{timeAgo(t.last_active)}</span>
                          <span>·</span>
                          <span>{t.message_count} msgs</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                {/* New thread input */}
                <div className={cn(
                  "border-t border-border bg-card/40 p-3",
                  threads.length === 0 && !loadingThreads && "flex-1 flex flex-col justify-center border-t-0",
                )}>
                  {threads.length === 0 && !loadingThreads && (
                    <p className="mb-3 text-center text-xs text-muted-foreground/50">
                      Start a conversation about this project
                    </p>
                  )}
                  {threads.length > 0 && (
                    <p className="mb-2 text-[0.65rem] font-semibold uppercase tracking-widest text-muted-foreground/60">
                      New thread
                    </p>
                  )}
                  <div className="flex gap-2">
                    <Input
                      ref={inputRef}
                      value={startMsg}
                      onChange={(e) => setStartMsg(e.target.value)}
                      placeholder="Ask Spark about this project…"
                      className="h-8 flex-1 text-xs"
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) {
                          e.preventDefault();
                          handleStartThread();
                        }
                      }}
                    />
                    <Button
                      size="sm"
                      className="h-8 w-8 shrink-0 p-0"
                      disabled={!startMsg.trim() || startingThread}
                      onClick={handleStartThread}
                    >
                      {startingThread ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Send className="h-3.5 w-3.5" />
                      )}
                    </Button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WorkspacePage() {
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [activeSlug, setActiveSlug] = useState<string | null>(null);

  // Tab state
  const [fileTabs, setFileTabs] = useState<FileTab[]>([]);
  const [activeTab, setActiveTab] = useState<ActiveTab>("chat");

  // Resizable panel widths (persisted to localStorage)
  const [[leftWidth, centerWidth], setWidths] = useState<[number, number]>(loadColWidths);

  const loadProjects = useCallback(async () => {
    setLoadingProjects(true);
    try {
      const res = await api.listWorkspaceProjects();
      setProjects(res.projects);
    } catch (e) {
      console.error("Load projects failed", e);
    } finally {
      setLoadingProjects(false);
    }
  }, []);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  const handleCreate = async (name: string) => {
    const res = await api.createWorkspaceProject(name);
    await loadProjects();
    setActiveSlug(res.slug);
  };

  // Clear file tabs when switching projects
  useEffect(() => {
    setFileTabs([]);
    setActiveTab("chat");
  }, [activeSlug]);

  // Drag handlers (incremental deltas from ResizeDivider)
  const handleLeftDrag = useCallback((delta: number) => {
    setWidths(([l, c]) => {
      const nl = Math.max(160, l + delta);
      saveColWidths(nl, c);
      return [nl, c];
    });
  }, []);

  const handleCenterDrag = useCallback((delta: number) => {
    setWidths(([l, c]) => {
      const nc = Math.max(200, c + delta);
      saveColWidths(l, nc);
      return [l, nc];
    });
  }, []);

  // Open or switch to a file tab
  const handleFileOpen = useCallback(
    async (node: WorkspaceFileNode, mime: string) => {
      const id = node.path;

      // Switch to existing tab if already open
      setFileTabs((prev) => {
        if (prev.find((t) => t.id === id)) return prev;
        const cat = getFileCategory(mime, node.name);
        const newTab: FileTab = {
          id,
          path: node.path,
          label: node.name,
          mime,
          content: null,
          loading: cat === "text",
        };
        return [...prev, newTab];
      });
      setActiveTab(id);

      // Fetch content for text files
      const cat = getFileCategory(mime, node.name);
      if (cat === "text") {
        try {
          const res = await api.getWorkspaceFile(activeSlug!, node.path);
          setFileTabs((prev) =>
            prev.map((t) => (t.id === id ? { ...t, content: res.content, loading: false } : t)),
          );
        } catch (e) {
          setFileTabs((prev) =>
            prev.map((t) =>
              t.id === id ? { ...t, content: `Error loading file: ${e}`, loading: false } : t,
            ),
          );
        }
      }
    },
    [activeSlug],
  );

  const handleTabClose = useCallback((id: string) => {
    setFileTabs((prev) => prev.filter((t) => t.id !== id));
    setActiveTab((prev) => (prev === id ? "chat" : prev));
  }, []);

  return (
    <div className="flex flex-1 overflow-hidden rounded-sm border border-border">
      {/* Left: project list */}
      <div style={{ width: leftWidth, minWidth: 160 }} className="shrink-0 overflow-hidden">
        <ProjectsSidebar
          projects={projects}
          activeSlug={activeSlug}
          onSelect={setActiveSlug}
          onCreate={handleCreate}
          loading={loadingProjects}
        />
      </div>

      <ResizeDivider onDrag={handleLeftDrag} />

      {/* Center: file tree */}
      <div style={{ width: centerWidth, minWidth: 200 }} className="shrink-0 overflow-hidden">
        {activeSlug ? (
          <FilePanel
            key={activeSlug}
            slug={activeSlug}
            onFileOpen={handleFileOpen}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center border-r border-border text-center">
            <FolderOpen className="mb-3 h-10 w-10 text-muted-foreground/20" />
            <p className="text-sm text-muted-foreground/50">Select a project</p>
          </div>
        )}
      </div>

      <ResizeDivider onDrag={handleCenterDrag} />

      {/* Right: chat + file viewer tabs */}
      <div className="flex-1 min-w-[280px] overflow-hidden">
        {activeSlug ? (
          <RightPanel
            key={`right-${activeSlug}`}
            slug={activeSlug}
            fileTabs={fileTabs}
            activeTab={activeTab}
            onTabClose={handleTabClose}
            onTabSelect={setActiveTab}
          />
        ) : (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <MessageSquare className="mb-3 h-10 w-10 text-muted-foreground/20" />
            <p className="text-sm text-muted-foreground/50">Select a project to chat</p>
          </div>
        )}
      </div>
    </div>
  );
}
