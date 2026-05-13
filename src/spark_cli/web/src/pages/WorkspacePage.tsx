import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  File,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
  MessageSquare,
  Plus,
  Send,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
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

// ── File tree node ───────────────────────────────────────────────────────────

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

// ── Projects sidebar ─────────────────────────────────────────────────────────

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

// ── File panel ───────────────────────────────────────────────────────────────

function FilePanel({
  slug,
  onFileSelect,
}: {
  slug: string;
  onFileSelect: (path: string, content: string) => void;
}) {
  const [tree, setTree] = useState<WorkspaceFileNode[]>([]);
  const [loadingTree, setLoadingTree] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string | null>(null);
  const [loadingFile, setLoadingFile] = useState(false);
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
    setFileContent(null);
    loadTree();
  }, [slug, loadTree]);

  const handleSelectFile = async (node: WorkspaceFileNode) => {
    setSelectedPath(node.path);
    setLoadingFile(true);
    setFileContent(null);
    try {
      const res = await api.getWorkspaceFile(slug, node.path);
      setFileContent(res.content);
      onFileSelect(node.path, res.content);
    } catch (e) {
      setFileContent(`Error loading file: ${e}`);
    } finally {
      setLoadingFile(false);
    }
  };

  const handleDelete = async (node: WorkspaceFileNode) => {
    if (!confirm(`Delete ${node.path}?`)) return;
    try {
      await api.deleteWorkspaceFile(slug, node.path);
      if (selectedPath === node.path) {
        setSelectedPath(null);
        setFileContent(null);
      }
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

      {/* File viewer */}
      {selectedPath && (
        <div className="flex max-h-64 flex-col border-t border-border">
          <div className="flex items-center justify-between bg-card/80 px-3 py-1.5 text-xs text-muted-foreground">
            <span className="truncate font-mono">{selectedPath}</span>
            <button
              type="button"
              onClick={() => {
                setSelectedPath(null);
                setFileContent(null);
              }}
            >
              <X className="h-3 w-3 hover:text-foreground" />
            </button>
          </div>
          <div className="flex-1 overflow-auto bg-background/60">
            {loadingFile ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <pre className="px-3 py-2 text-[0.68rem] leading-relaxed text-muted-foreground font-mono whitespace-pre-wrap break-all">
                {fileContent}
              </pre>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Project chat panel ────────────────────────────────────────────────────────

function ProjectChatPanel({ slug }: { slug: string }) {
  const [threads, setThreads] = useState<SessionInfo[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loadingThreads, setLoadingThreads] = useState(false);
  const [startMsg, setStartMsg] = useState("");
  const [startingThread, setStartingThread] = useState(false);

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

  useEventBus((env: SparkEventEnvelope) => {
    if (env.topic === "sessions.changed") {
      const src = (env.data as { session?: { source?: string } }).session?.source ?? "";
      if (src === `workspace:${slug}`) {
        loadThreads();
      }
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
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border bg-card/60 px-3 py-3">
        <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          Chat
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
        /* Active thread chat */
        <ChatPanel
          sessionId={activeId}
          sessionTitle={activeThread?.title ?? activeThread?.preview ?? "Thread"}
          onBack={() => setActiveId(null)}
          onSessionCreated={(id) => setActiveId(id)}
          onSessionUpdated={() => loadThreads()}
          className="min-h-0 flex-1"
        />
      ) : (
        /* Thread list + new thread input */
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Thread list */}
          <div className="flex-1 overflow-y-auto">
            {loadingThreads && threads.length === 0 && (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              </div>
            )}
            {!loadingThreads && threads.length === 0 && (
              <p className="px-4 py-8 text-center text-xs text-muted-foreground/60">
                No threads yet. Start a conversation below.
              </p>
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

          {/* New thread input */}
          <div className="border-t border-border bg-card/40 p-3">
            <p className="mb-2 text-[0.65rem] font-semibold uppercase tracking-widest text-muted-foreground/60">
              New thread
            </p>
            <div className="flex gap-2">
              <Input
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
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function WorkspacePage() {
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [activeSlug, setActiveSlug] = useState<string | null>(null);

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

  const [_selectedFilePath, setSelectedFilePath] = useState<string | null>(null);

  return (
    <div
      className="grid h-[calc(100vh-6rem)] sm:h-[calc(100vh-8rem)] overflow-hidden rounded-sm border border-border"
      style={{ gridTemplateColumns: "240px 300px 1fr" }}
    >
      {/* Left: project list */}
      <ProjectsSidebar
        projects={projects}
        activeSlug={activeSlug}
        onSelect={setActiveSlug}
        onCreate={handleCreate}
        loading={loadingProjects}
      />

      {/* Center: file tree + viewer */}
      {activeSlug ? (
        <FilePanel
          key={activeSlug}
          slug={activeSlug}
          onFileSelect={(path) => setSelectedFilePath(path)}
        />
      ) : (
        <div className="flex flex-col items-center justify-center border-r border-border text-center">
          <FolderOpen className="mb-3 h-10 w-10 text-muted-foreground/20" />
          <p className="text-sm text-muted-foreground/50">Select a project</p>
        </div>
      )}

      {/* Right: chat threads */}
      {activeSlug ? (
        <ProjectChatPanel key={`chat-${activeSlug}`} slug={activeSlug} />
      ) : (
        <div className="flex flex-col items-center justify-center text-center">
          <MessageSquare className="mb-3 h-10 w-10 text-muted-foreground/20" />
          <p className="text-sm text-muted-foreground/50">Select a project to chat</p>
        </div>
      )}
    </div>
  );
}
