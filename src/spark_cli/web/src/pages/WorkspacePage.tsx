import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bot,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Edit3,
  File,
  FileText,
  Folder,
  FolderOpen,
  GripVertical,
  Loader2,
  MessageSquare,
  Plus,
  Search,
  Send,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api, workspaceRawFileUrl } from "@/lib/api";
import type { SessionInfo, WorkspaceFileNode, WorkspaceProject } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatPanel } from "@/components/ChatPanel";
import { useEventBus } from "@/hooks/useEventBus";
import type { SparkEventEnvelope } from "@/hooks/useEventBus";
import { ThreadRow, threadTitle } from "@/components/chat/ThreadRow";

// ── Types ─────────────────────────────────────────────────────────────────────

type FileView = {
  path: string;
  name: string;
  mime: string;
  content: string | null;
  loading: boolean;
};

// ── File utilities ─────────────────────────────────────────────────────────────

function getFileCategory(mime: string, filename: string): "text" | "image" | "video" | "binary" {
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (
    mime.startsWith("text/") ||
    ["application/json", "application/yaml", "application/xml"].includes(mime)
  )
    return "text";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const textExts = new Set([
    "ts", "tsx", "js", "jsx", "py", "md", "txt", "yaml", "yml",
    "json", "html", "css", "sh", "toml", "env", "ini", "cfg",
  ]);
  return textExts.has(ext) ? "text" : "binary";
}

function FileIcon({ name }: { name: string }) {
  const ext = name.split(".").pop()?.toLowerCase() ?? "";
  const textExts = new Set([
    "ts", "tsx", "js", "jsx", "py", "md", "txt", "yaml", "yml", "json",
    "html", "css", "sh", "toml", "env", "ini", "cfg",
  ]);
  return textExts.has(ext) ? (
    <FileText className="h-3.5 w-3.5 shrink-0 text-sky-300/70" />
  ) : (
    <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
  );
}

// ── File tree node ─────────────────────────────────────────────────────────────

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
          if (isDir) setExpanded((v) => !v);
          else onSelect(node);
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
              <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-300/80" />
            ) : (
              <Folder className="h-3.5 w-3.5 shrink-0 text-amber-300/80" />
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
            className="ml-1 hidden text-muted-foreground/50 hover:text-destructive group-hover:block"
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
              className="px-2 py-0.5 text-xs italic text-muted-foreground/40"
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

// ── File viewer ───────────────────────────────────────────────────────────────

function FileViewer({ file, slug }: { file: FileView; slug: string }) {
  const cat = getFileCategory(file.mime, file.name);

  if (file.loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (cat === "image") {
    const url = workspaceRawFileUrl(slug, file.path);
    return (
      <div className="flex h-full flex-col items-center gap-3 overflow-auto p-4">
        <img
          src={url}
          alt={file.name}
          className="max-w-full rounded border border-border object-contain"
        />
        <a
          href={url}
          download={file.name}
          className="text-xs text-muted-foreground underline hover:text-foreground"
        >
          Download {file.name}
        </a>
      </div>
    );
  }

  if (cat === "video") {
    const url = workspaceRawFileUrl(slug, file.path);
    return (
      <div className="flex h-full flex-col items-center gap-3 overflow-auto p-4">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video src={url} controls className="max-w-full rounded border border-border" />
        <a
          href={url}
          download={file.name}
          className="text-xs text-muted-foreground underline hover:text-foreground"
        >
          Download {file.name}
        </a>
      </div>
    );
  }

  if (cat === "text" && file.content !== null) {
    return (
      <div className="h-full overflow-auto bg-background/60">
        <pre className="whitespace-pre-wrap break-all px-4 py-3 font-mono text-[0.7rem] leading-relaxed text-muted-foreground">
          {file.content}
        </pre>
      </div>
    );
  }

  const url = workspaceRawFileUrl(slug, file.path);
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
      <File className="h-10 w-10 text-muted-foreground/20" />
      <p className="text-xs text-muted-foreground/60">Binary file — no preview available.</p>
      <a href={url} download={file.name} className="text-xs text-primary hover:underline">
        Download {file.name}
      </a>
    </div>
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
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border transition-colors group-hover:bg-primary/50 group-active:bg-primary/70" />
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
  collapsed,
  onToggleCollapse,
  panelWidth,
}: {
  projects: WorkspaceProject[];
  activeSlug: string | null;
  onSelect: (slug: string) => void;
  onCreate: (name: string) => Promise<void>;
  loading: boolean;
  collapsed: boolean;
  onToggleCollapse: () => void;
  panelWidth: number;
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

  if (collapsed) {
    return (
      <div className="flex w-10 shrink-0 flex-col items-center gap-1 border-r border-border bg-card/60 py-2">
        <button
          type="button"
          title="Show projects"
          onClick={onToggleCollapse}
          className="rounded p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
        <div className="my-1 h-px w-6 bg-border" />
        {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground/50" />}
        {projects.map((p) => (
          <button
            key={p.slug}
            type="button"
            title={p.name}
            onClick={() => {
              onSelect(p.slug);
              onToggleCollapse();
            }}
            className={cn(
              "rounded p-1.5 transition",
              activeSlug === p.slug
                ? "bg-primary/15 text-primary"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            <FolderOpen className="h-3.5 w-3.5" />
          </button>
        ))}
        <button
          type="button"
          title="New project"
          onClick={() => {
            onToggleCollapse();
            setTimeout(() => setCreating(true), 150);
          }}
          className="rounded p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div style={{ width: panelWidth }} className="flex shrink-0 flex-col overflow-hidden border-r border-border bg-card/60">
      <div className="shrink-0 border-b border-border p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <FolderOpen className="h-4 w-4 text-muted-foreground" />
              <h2 className="truncate text-sm font-semibold">Projects</h2>
            </div>
            <p className="mt-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              Workspace
            </p>
          </div>
          <div className="flex items-center gap-0.5 shrink-0">
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-7 p-0"
              title="New project"
              onClick={() => setCreating(true)}
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-7 p-0"
              title="Collapse projects"
              onClick={onToggleCollapse}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-1">
        {loading && projects.length === 0 && (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        )}
        {!loading && projects.length === 0 && !creating && (
          <p className="px-3 py-4 text-center text-xs text-muted-foreground/60">
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
              "w-full px-3 py-2 text-left text-sm transition",
              activeSlug === p.slug
                ? "border-r-2 border-primary bg-primary/15 text-foreground"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            <div className="flex items-center gap-2">
              <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-300/70" />
              <span className="truncate font-medium">{p.name}</span>
            </div>
            <div className="mt-0.5 pl-5 text-xs text-muted-foreground/50">
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
                if (e.key === "Enter") void handleCreate();
                if (e.key === "Escape") {
                  setCreating(false);
                  setNewName("");
                }
              }}
            />
            <div className="flex gap-1">
              <Button
                size="sm"
                className="h-6 flex-1 text-xs"
                onClick={() => void handleCreate()}
                disabled={saving}
              >
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

// ── Workspace thread list ─────────────────────────────────────────────────────

function WorkspaceThreadList({
  slug,
  activeId,
  onOpen,
  onNewThread,
  onSessionsChange,
  panelWidth,
}: {
  slug: string;
  activeId: string | null;
  onOpen: (id: string, session: SessionInfo) => void;
  onNewThread: () => void;
  onSessionsChange: (sessions: SessionInfo[]) => void;
  panelWidth: number;
}) {
  const [threads, setThreads] = useState<SessionInfo[]>([]);
  const [loadingThreads, setLoadingThreads] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const loadThreads = useCallback(async () => {
    setLoadingThreads(true);
    try {
      const res = await api.listWorkspaceConversations(slug);
      const sessions = res.sessions as SessionInfo[];
      setThreads(sessions);
      onSessionsChange(sessions);
    } catch (e) {
      console.error("Load threads failed", e);
    } finally {
      setLoadingThreads(false);
    }
  }, [slug, onSessionsChange]);

  useEffect(() => {
    setThreads([]);
    setSearchQ("");
    loadThreads();
  }, [slug, loadThreads]);

  useEventBus((env: SparkEventEnvelope) => {
    if (env.topic === "sessions.changed") {
      const src = (env.data as { session?: { source?: string } }).session?.source ?? "";
      if (src === `workspace:${slug}`) void loadThreads();
    }
  });

  const handleDelete = async (id: string) => {
    setThreads((prev) => {
      const next = prev.filter((t) => t.id !== id);
      onSessionsChange(next);
      return next;
    });
    try {
      await api.deleteSession(id);
    } catch {
      void loadThreads();
    }
  };

  const visibleThreads = searchQ.trim()
    ? threads.filter((t) => {
        const q = searchQ.toLowerCase();
        return t.title?.toLowerCase().includes(q) || t.preview?.toLowerCase().includes(q);
      })
    : threads;

  return (
    <div style={{ width: panelWidth }} className="flex shrink-0 flex-col overflow-hidden border-r border-border">
      {/* Header */}
      <div className="shrink-0 border-b border-border p-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-muted-foreground" />
              <h2 className="truncate text-sm font-semibold">Threads</h2>
              <Badge variant="secondary" className="h-5 text-[10px]">
                {threads.length}
              </Badge>
            </div>
            <p className="mt-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              Project chats
            </p>
          </div>
          <Button
            size="sm"
            className="h-8 shrink-0 gap-1.5"
            onClick={onNewThread}
          >
            <Plus className="h-3.5 w-3.5" />
            New
          </Button>
        </div>
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            ref={searchInputRef}
            className="h-9 pl-8 pr-16 text-sm"
            placeholder="Search threads…"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
          />
          {!searchQ && (
            <kbd className="pointer-events-none absolute right-8 top-1/2 -translate-y-1/2 rounded border border-border bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
              ⌘K
            </kbd>
          )}
          {searchQ && (
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              onClick={() => setSearchQ("")}
              aria-label="Clear search"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Thread list */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {loadingThreads && threads.length === 0 && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
          </div>
        )}
        {visibleThreads.map((t) => (
          <ThreadRow
            key={t.id}
            session={t}
            active={activeId === t.id}
            onOpen={() => onOpen(t.id, t)}
            onDelete={() => void handleDelete(t.id)}
          />
        ))}
        {!loadingThreads && visibleThreads.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center px-8 py-12 text-center text-muted-foreground">
            <Bot className="mb-3 h-9 w-9 opacity-35" />
            <p className="text-sm font-medium">
              {searchQ ? "No matching threads" : "No threads yet"}
            </p>
            <p className="mt-1 text-xs opacity-70">
              {searchQ ? "Try a different search." : "Click New to start one."}
            </p>
          </div>
        )}
      </div>

    </div>
  );
}

// ── New thread (full-area, like Chat tab) ─────────────────────────────────────

function WorkspaceNewThread({
  slug,
  onCreated,
  onCancel,
}: {
  slug: string;
  onCreated: (id: string, initialMsg: string) => void;
  onCancel: () => void;
}) {
  const [msg, setMsg] = useState("");
  const [starting, setStarting] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setTimeout(() => textareaRef.current?.focus(), 50);
  }, []);

  const handleSend = async () => {
    const text = msg.trim();
    if (!text || starting) return;
    setStarting(true);
    try {
      const res = await api.startWorkspaceConversation(slug, text);
      onCreated(res.session_id, text);
    } catch (e) {
      console.error("Failed to start conversation", e);
      setStarting(false);
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* Header — matches session header style */}
      <div className="hidden shrink-0 items-center justify-between gap-3 border-b border-border bg-background/70 px-4 py-2 md:flex">
        <p className="text-sm font-medium">New thread</p>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 shrink-0 gap-1.5 px-2 text-xs"
          onClick={onCancel}
        >
          <X className="h-3.5 w-3.5" />
          Cancel
        </Button>
      </div>

      {/* Empty messages area */}
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center text-muted-foreground">
        <MessageSquare className="mb-4 h-12 w-12 opacity-20" />
        <p className="text-sm font-medium text-foreground">Start a conversation</p>
        <p className="mt-1 max-w-sm text-xs opacity-75">
          Ask Spark anything about this project — it has context of the workspace files.
        </p>
      </div>

      {/* Prompt bar — matches Chat tab's PromptBar style */}
      <div className="shrink-0 border-t border-border bg-card/40 p-3">
        <div className="relative flex items-end gap-2 rounded-lg border border-border bg-background px-3 py-2 focus-within:ring-1 focus-within:ring-primary/50">
          <textarea
            ref={textareaRef}
            value={msg}
            onChange={(e) => {
              setMsg(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`;
            }}
            placeholder="Ask Spark about this project…"
            rows={1}
            className="flex-1 resize-none bg-transparent text-sm leading-relaxed outline-none placeholder:text-muted-foreground"
            style={{ maxHeight: 200 }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void handleSend();
              }
              if (e.key === "Escape") onCancel();
            }}
          />
          <Button
            size="sm"
            className="mb-0.5 h-8 w-8 shrink-0 p-0"
            disabled={!msg.trim() || starting}
            onClick={() => void handleSend()}
          >
            {starting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
        <p className="mt-1.5 text-center text-[10px] text-muted-foreground/50">
          Enter to send · Shift+Enter for new line · Esc to cancel
        </p>
      </div>
    </div>
  );
}

// ── Files panel ───────────────────────────────────────────────────────────────

function FilesPanel({
  slug,
  collapsed,
  onToggleCollapse,
  panelWidth,
}: {
  slug: string;
  collapsed: boolean;
  onToggleCollapse: () => void;
  panelWidth: number;
}) {
  const [tree, setTree] = useState<WorkspaceFileNode[]>([]);
  const [loadingTree, setLoadingTree] = useState(false);
  const [selectedFile, setSelectedFile] = useState<FileView | null>(null);
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
    setSelectedFile(null);
    loadTree();
  }, [slug, loadTree]);

  const handleSelectFile = async (node: WorkspaceFileNode) => {
    const mime = node.mime ?? "application/octet-stream";
    const cat = getFileCategory(mime, node.name);
    const file: FileView = {
      path: node.path,
      name: node.name,
      mime,
      content: null,
      loading: cat === "text",
    };
    setSelectedFile(file);

    if (cat === "text") {
      try {
        const res = await api.getWorkspaceFile(slug, node.path);
        setSelectedFile((prev) =>
          prev?.path === node.path ? { ...prev, content: res.content, loading: false } : prev,
        );
      } catch (e) {
        setSelectedFile((prev) =>
          prev?.path === node.path
            ? { ...prev, content: `Error loading file: ${e}`, loading: false }
            : prev,
        );
      }
    }
  };

  const handleDelete = async (node: WorkspaceFileNode) => {
    if (!confirm(`Delete ${node.path}?`)) return;
    try {
      await api.deleteWorkspaceFile(slug, node.path);
      if (selectedFile?.path === node.path) setSelectedFile(null);
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

  if (collapsed) {
    return (
      <div className="flex w-10 shrink-0 flex-col items-center gap-1 border-l border-border bg-card/60 py-2">
        <button
          type="button"
          title="Show files"
          onClick={onToggleCollapse}
          className="rounded p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <div className="my-1 h-px w-6 bg-border" />
        <button
          type="button"
          title="Files"
          onClick={onToggleCollapse}
          className="rounded p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
        >
          <FileText className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          title="Upload files"
          onClick={() => fileInputRef.current?.click()}
          className="rounded p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
        >
          <Upload className="h-3.5 w-3.5" />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => e.target.files && void handleUpload(e.target.files)}
        />
      </div>
    );
  }

  return (
    <div style={{ width: panelWidth }} className="flex shrink-0 flex-col overflow-hidden border-l border-border">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-border bg-card/60 px-3 py-3">
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
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0"
            title="Collapse files"
            onClick={onToggleCollapse}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => e.target.files && void handleUpload(e.target.files)}
          />
        </div>
      </div>

      {/* File tree */}
      <div
        className={cn(
          "overflow-y-auto py-1 transition-all",
          selectedFile ? "h-[45%]" : "flex-1",
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
          if (e.dataTransfer.files.length) void handleUpload(e.dataTransfer.files);
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
            onSelect={(n) => void handleSelectFile(n)}
            selectedPath={selectedFile?.path ?? null}
            onDelete={(n) => void handleDelete(n)}
          />
        ))}
      </div>

      {/* Inline file viewer */}
      {selectedFile && (
        <div className="flex flex-col overflow-hidden border-t border-border" style={{ flex: "0 0 55%" }}>
          <div className="flex shrink-0 items-center justify-between border-b border-border bg-card/60 px-3 py-1.5">
            <span className="truncate text-xs text-muted-foreground" title={selectedFile.path}>
              {selectedFile.name}
            </span>
            <button
              type="button"
              className="ml-2 shrink-0 text-muted-foreground/50 hover:text-foreground"
              onClick={() => setSelectedFile(null)}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            <FileViewer file={selectedFile} slug={slug} />
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WorkspacePage() {
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [activeSlug, setActiveSlug] = useState<string | null>(null);

  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [activeSession, setActiveSession] = useState<SessionInfo | null>(null);
  const [pendingInitialMsg, setPendingInitialMsg] = useState<string | null>(null);
  const [newThread, setNewThread] = useState(false);

  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  const [projectsCollapsed, setProjectsCollapsed] = useState<boolean>(() => {
    return localStorage.getItem("spark-workspace-projects-collapsed") === "true";
  });
  const [filesCollapsed, setFilesCollapsed] = useState<boolean>(() => {
    return localStorage.getItem("spark-workspace-files-collapsed") === "true";
  });

  const [[projectsWidth, threadsWidth, filesWidth], setPanelWidths] = useState<[number, number, number]>(() => {
    try {
      const raw = localStorage.getItem("spark-workspace-widths");
      if (raw) {
        const p = JSON.parse(raw) as unknown;
        if (Array.isArray(p) && p.length === 3 && p.every((x) => typeof x === "number"))
          return [Math.max(160, p[0] as number), Math.max(200, p[1] as number), Math.max(200, p[2] as number)];
      }
    } catch { /* ignore */ }
    return [220, 300, 280];
  });

  const handleProjectsDrag = useCallback((delta: number) => {
    setPanelWidths(([p, t, f]) => {
      const next: [number, number, number] = [Math.max(160, p + delta), t, f];
      localStorage.setItem("spark-workspace-widths", JSON.stringify(next));
      return next;
    });
  }, []);

  const handleThreadsDrag = useCallback((delta: number) => {
    setPanelWidths(([p, t, f]) => {
      const next: [number, number, number] = [p, Math.max(200, t + delta), f];
      localStorage.setItem("spark-workspace-widths", JSON.stringify(next));
      return next;
    });
  }, []);

  const handleFilesDrag = useCallback((delta: number) => {
    setPanelWidths(([p, t, f]) => {
      const next: [number, number, number] = [p, t, Math.max(200, f - delta)];
      localStorage.setItem("spark-workspace-widths", JSON.stringify(next));
      return next;
    });
  }, []);

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
    void loadProjects();
  }, [loadProjects]);

  const handleCreate = async (name: string) => {
    const res = await api.createWorkspaceProject(name);
    await loadProjects();
    setActiveSlug(res.slug);
    setActiveThreadId(null);
    setActiveSession(null);
  };

  const handleSelectProject = (slug: string) => {
    setActiveSlug(slug);
    setActiveThreadId(null);
    setActiveSession(null);
    setPendingInitialMsg(null);
    setNewThread(false);
    setEditingTitle(false);
  };

  const handleOpenThread = (id: string, session: SessionInfo) => {
    setActiveThreadId(id);
    setActiveSession(session);
    setPendingInitialMsg(null);
    setNewThread(false);
    setEditingTitle(false);
  };

  const handleNewThread = () => {
    setActiveThreadId(null);
    setActiveSession(null);
    setNewThread(true);
    setEditingTitle(false);
  };

  const handleThreadCreated = (id: string, initialMsg: string) => {
    setActiveThreadId(id);
    setPendingInitialMsg(initialMsg);
    setNewThread(false);
  };

  const handleSessionsChange = useCallback(
    (sessions: SessionInfo[]) => {
      if (activeThreadId) {
        const updated = sessions.find((s) => s.id === activeThreadId);
        if (updated) setActiveSession(updated);
      }
    },
    [activeThreadId],
  );

  const toggleProjectsCollapse = () => {
    setProjectsCollapsed((v) => {
      const next = !v;
      localStorage.setItem("spark-workspace-projects-collapsed", String(next));
      return next;
    });
  };

  const toggleFilesCollapse = () => {
    setFilesCollapsed((v) => {
      const next = !v;
      localStorage.setItem("spark-workspace-files-collapsed", String(next));
      return next;
    });
  };

  const beginRename = () => {
    if (!activeSession) return;
    setTitleDraft(activeSession.title || "");
    setEditingTitle(true);
  };

  const saveRename = async () => {
    if (!activeSession) return;
    try {
      await api.renameSession(activeSession.id, titleDraft);
      setActiveSession((prev) => (prev ? { ...prev, title: titleDraft } : prev));
      setEditingTitle(false);
    } catch (e) {
      console.error("Rename failed", e);
    }
  };

  return (
    <div className="flex h-full max-h-screen min-h-0 overflow-hidden border-t border-border bg-card/75">
      {/* Projects panel */}
      <ProjectsSidebar
        projects={projects}
        activeSlug={activeSlug}
        onSelect={handleSelectProject}
        onCreate={handleCreate}
        loading={loadingProjects}
        collapsed={projectsCollapsed}
        onToggleCollapse={toggleProjectsCollapse}
        panelWidth={projectsWidth}
      />

      {/* Divider: projects ↔ threads/chat */}
      {!projectsCollapsed && <ResizeDivider onDrag={handleProjectsDrag} />}

      {/* Thread list — only when a project is active */}
      {activeSlug && (
        <>
          <WorkspaceThreadList
            key={activeSlug}
            slug={activeSlug}
            activeId={activeThreadId}
            onOpen={handleOpenThread}
            onNewThread={handleNewThread}
            onSessionsChange={handleSessionsChange}
            panelWidth={threadsWidth}
          />
          <ResizeDivider onDrag={handleThreadsDrag} />
        </>
      )}

      {/* Chat area */}
      <div className="flex min-w-0 flex-1 flex-col">
        {activeSlug ? (
          newThread ? (
            <WorkspaceNewThread
              key={`new-${activeSlug}`}
              slug={activeSlug}
              onCreated={handleThreadCreated}
              onCancel={() => setNewThread(false)}
            />
          ) : activeThreadId ? (
            <>
              {/* Session header */}
              <div className="hidden shrink-0 items-center justify-between gap-3 border-b border-border bg-background/70 px-4 py-2 md:flex">
                <div className="min-w-0 flex-1">
                  {editingTitle ? (
                    <div className="flex max-w-xl items-center gap-2">
                      <Input
                        className="h-8 text-sm"
                        value={titleDraft}
                        placeholder={activeSession?.preview || "Thread title"}
                        onChange={(e) => setTitleDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") void saveRename();
                          if (e.key === "Escape") setEditingTitle(false);
                        }}
                        autoFocus
                      />
                      <Button size="icon" className="h-8 w-8" onClick={() => void saveRename()}>
                        <Check className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8"
                        onClick={() => setEditingTitle(false)}
                      >
                        <X className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ) : (
                    <div className="flex min-w-0 items-center gap-2">
                      <p className="truncate text-sm font-medium">
                        {activeSession ? threadTitle(activeSession) : "Thread"}
                      </p>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-muted-foreground"
                        onClick={beginRename}
                      >
                        <Edit3 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  )}
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 shrink-0 gap-1.5 px-2 text-xs"
                  onClick={() => {
                    setActiveThreadId(null);
                    setActiveSession(null);
                    setEditingTitle(false);
                    setPendingInitialMsg(null);
                  }}
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                  All threads
                </Button>
              </div>

              <ChatPanel
                sessionId={activeThreadId}
                sessionTitle={activeSession ? threadTitle(activeSession) : null}
                initialMessage={pendingInitialMsg ?? undefined}
                onBack={() => {
                  setActiveThreadId(null);
                  setActiveSession(null);
                  setPendingInitialMsg(null);
                }}
                onSessionCreated={(id) => setActiveThreadId(id)}
                onSessionUpdated={() => {}}
                className="min-h-0 flex-1"
              />
            </>
          ) : (
            <div className="flex h-full flex-col items-center justify-center px-6 text-center text-muted-foreground">
              <MessageSquare className="mb-4 h-12 w-12 opacity-30" />
              <p className="text-sm font-medium text-foreground">Select a thread</p>
              <p className="mt-1 max-w-sm text-xs opacity-75">
                Pick a thread from the list or click New to start one.
              </p>
            </div>
          )
        ) : (
          <div className="flex h-full flex-col items-center justify-center px-6 text-center text-muted-foreground">
            <FolderOpen className="mb-4 h-12 w-12 opacity-30" />
            <p className="text-sm font-medium text-foreground">Select a project</p>
            <p className="mt-1 max-w-sm text-xs opacity-75">
              Choose a project from the left panel to get started.
            </p>
          </div>
        )}
      </div>

      {/* Files panel — only when a project is active */}
      {activeSlug && (
        <>
          {!filesCollapsed && <ResizeDivider onDrag={handleFilesDrag} />}
          <FilesPanel
            key={`files-${activeSlug}`}
            slug={activeSlug}
            collapsed={filesCollapsed}
            onToggleCollapse={toggleFilesCollapse}
            panelWidth={filesWidth}
          />
        </>
      )}
    </div>
  );
}
