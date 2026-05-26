import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  Brush,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CheckSquare,
  File,
  FileText,
  FolderOpen,
  Loader2,
  Menu,
  MessageSquare,
  PanelRight,
  Plus,
  Search,
  SquareTerminal,
  Trash2,
  X,
} from "lucide-react";
import hljs from "highlight.js";
import { api, workspaceRawFileUrl } from "@/lib/api";
import type { SessionInfo, WorkspaceFileNode, WorkspaceProject } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import {
  addSessionNotification,
  dismissSessionNotification,
  getUnreadSessionIds,
  markSessionRead,
  subscribeToUnreadSessions,
} from "@/lib/unreadSessionStore";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatPanel } from "@/components/ChatPanel";
import { PromptBar } from "@/components/chat/PromptBar";
import { useEventBus } from "@/hooks/useEventBus";
import type { SparkEventEnvelope } from "@/hooks/useEventBus";
import { threadTitle } from "@/components/chat/ThreadRow";
import { FileTreePane, getFileCategory } from "@/components/workspace/FileTreePane";
import { WorkspaceTerminalPanel } from "@/components/workspace/WorkspaceTerminalPanel";

// ── Helpers ───────────────────────────────────────────────────────────────────

function slugFromSource(source: string | null): string | null {
  if (!source?.startsWith("workspace:")) return null;
  return source.slice("workspace:".length);
}

function languageForFile(filename: string): string | null {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    bash: "bash", css: "css", env: "ini", html: "xml", ini: "ini",
    js: "javascript", jsx: "javascript", json: "json", md: "markdown",
    py: "python", sh: "bash", ts: "typescript", tsx: "typescript",
    toml: "ini", txt: "plaintext", xml: "xml", yaml: "yaml", yml: "yaml",
  };
  return map[ext] ?? null;
}

// ── CompactThreadRow ──────────────────────────────────────────────────────────

function CompactThreadRow({
  session,
  active,
  indent = false,
  selectMode = false,
  selected = false,
  unread = false,
  onOpen,
  onDelete,
  onToggleSelect,
}: {
  session: SessionInfo;
  active: boolean;
  indent?: boolean;
  selectMode?: boolean;
  selected?: boolean;
  unread?: boolean;
  onOpen: () => void;
  onDelete: () => void;
  onToggleSelect?: () => void;
}) {
  const handleClick = () => {
    if (selectMode) { onToggleSelect?.(); return; }
    onOpen();
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleClick(); } }}
      className={cn(
        "group relative flex w-full min-w-0 cursor-pointer select-none items-center gap-2 rounded-sm py-1.5 pr-2 text-left transition",
        indent ? "pl-8" : "pl-3",
        selectMode && selected ? "bg-primary/15 text-foreground" : active ? "bg-primary/12 text-foreground" : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
      )}
    >
      {selectMode ? (
        <span className={cn(
          "h-3.5 w-3.5 shrink-0 rounded-sm border transition",
          selected ? "border-primary bg-primary" : "border-muted-foreground/40 bg-transparent",
        )} />
      ) : (
        <MessageSquare className={cn("h-3.5 w-3.5 shrink-0", active ? "text-primary" : "text-muted-foreground/60")} />
      )}
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium leading-5">
        {threadTitle(session)}
      </span>
      {!selectMode && unread && (
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" title="New response" />
      )}
      {!selectMode && (
        <>
          <span className="shrink-0 text-[10px] text-muted-foreground/50 group-hover:hidden">
            {timeAgo(session.last_active)}
          </span>
          <button
            type="button"
            className="absolute right-1.5 hidden rounded p-0.5 text-muted-foreground/50 hover:text-destructive group-hover:block"
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            aria-label="Delete thread"
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </>
      )}
    </div>
  );
}

// ── ProjectFolder ─────────────────────────────────────────────────────────────

function ProjectFolder({
  project,
  threads,
  isExpanded,
  selectedId,
  onToggle,
  onSelect,
  onDelete,
  onNewThread,
  onDeleteProject,
  selectMode = false,
  selectedBulkIds,
  onToggleSelect,
  unreadSessionIds,
}: {
  project: WorkspaceProject;
  threads: SessionInfo[];
  isExpanded: boolean;
  selectedId: string | null;
  onToggle: () => void;
  onSelect: (id: string, session: SessionInfo) => void;
  onDelete: (id: string) => void;
  onNewThread: (slug: string) => void;
  onDeleteProject: (slug: string) => void;
  selectMode?: boolean;
  selectedBulkIds?: Set<string>;
  onToggleSelect?: (id: string) => void;
  unreadSessionIds?: Set<string>;
}) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  return (
    <div>
      {/* Folder header */}
      <div className="group flex items-center gap-1.5 rounded-sm px-2 py-1.5 transition hover:bg-secondary/50">
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
          onClick={onToggle}
        >
          <span className="text-muted-foreground/50">
            {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </span>
          <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-300/70" />
          <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground/80">
            {project.name}
          </span>
          {threads.length > 0 && (
            <Badge variant="secondary" className="h-4 shrink-0 px-1 text-[10px]">
              {threads.length}
            </Badge>
          )}
        </button>
        {/* Action buttons — visible on hover */}
        <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
          <button
            type="button"
            title="New thread in this project"
            className="rounded p-0.5 text-muted-foreground/60 hover:text-foreground"
            onClick={(e) => { e.stopPropagation(); onNewThread(project.slug); }}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="Delete project"
            className="rounded p-0.5 text-muted-foreground/60 hover:text-destructive"
            onClick={(e) => { e.stopPropagation(); setShowDeleteConfirm(true); }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Delete confirm */}
      {showDeleteConfirm && (
        <div className="mx-2 mb-1 rounded-sm border border-destructive/40 bg-background p-2 text-xs">
          <p className="mb-1.5 text-foreground">Delete <span className="font-semibold">{project.name}</span>?</p>
          <p className="mb-2 text-muted-foreground">Removes all project files permanently.</p>
          <div className="flex gap-1">
            <Button size="sm" variant="destructive" className="h-6 flex-1 text-xs" onClick={() => { onDeleteProject(project.slug); setShowDeleteConfirm(false); }}>
              Delete
            </Button>
            <Button size="sm" variant="ghost" className="h-6 w-6 p-0" onClick={() => setShowDeleteConfirm(false)}>
              <X className="h-3 w-3" />
            </Button>
          </div>
        </div>
      )}

      {/* Thread list (when expanded) */}
      {isExpanded && (
        <div className="pb-1">
          {threads.length === 0 ? (
            <p className="py-1.5 pl-10 text-[11px] italic text-muted-foreground/40">No chats</p>
          ) : (
            threads.map((t) => (
              <CompactThreadRow
                key={t.id}
                session={t}
                active={selectedId === t.id}
                indent
                selectMode={selectMode}
                selected={selectedBulkIds?.has(t.id) ?? false}
                unread={unreadSessionIds?.has(t.id) ?? false}
                onOpen={() => onSelect(t.id, t)}
                onDelete={() => onDelete(t.id)}
                onToggleSelect={() => onToggleSelect?.(t.id)}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── NewThreadCompose ──────────────────────────────────────────────────────────

function NewThreadCompose({
  projectSlug,
  projectName,
  onCreated,
  onCancel,
}: {
  projectSlug: string | null;
  projectName: string | null;
  onCreated: (sessionId: string, initialMessage: string) => void;
  onCancel: () => void;
}) {
  const [msg, setMsg] = useState("");
  const [starting, setStarting] = useState(false);

  const handleSend = async () => {
    const text = msg.trim();
    if (!text || starting) return;
    setStarting(true);
    try {
      if (projectSlug) {
        const res = await api.startWorkspaceConversation(projectSlug, text);
        onCreated(res.session_id, text);
      } else {
        const res = await api.postConversation(text);
        onCreated(res.session_id, text);
      }
    } catch (e) {
      console.error("Failed to start conversation", e);
      setStarting(false);
    }
  };

  const handleUpload = async (files: File[]) => {
    if (!projectSlug) return;
    const res = await api.uploadWorkspaceFiles(projectSlug, files, "files");
    const refs = res.saved.map((f) => `@files/${f.filename}`).join(" ");
    setMsg((prev) => {
      const prefix = prev.trimEnd();
      return prefix ? `${prefix}\n${refs} ` : `${refs} `;
    });
  };

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border bg-background/70 px-4 py-2">
        <p className="text-sm font-medium">
          {projectSlug ? `New thread in ${projectName ?? projectSlug}` : "New chat"}
        </p>
        <Button size="sm" variant="ghost" className="h-7 gap-1.5 px-2 text-xs" onClick={onCancel}>
          <X className="h-3.5 w-3.5" />
          Cancel
        </Button>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center text-muted-foreground">
        <MessageSquare className="mb-4 h-12 w-12 opacity-20" />
        <p className="text-sm font-medium text-foreground">
          {projectSlug ? "Start a project conversation" : "Start a conversation"}
        </p>
        <p className="mt-1 max-w-sm text-xs opacity-75">
          {projectSlug
            ? "Spark has context of the workspace files for this project."
            : "Ask Spark anything — tools, code, research, or just chat."}
        </p>
      </div>
      <PromptBar
        input={msg}
        setInput={setMsg}
        streaming={false}
        onSend={() => void handleSend()}
        onStop={() => {}}
        onUploadFiles={projectSlug ? handleUpload : undefined}
        disabled={starting}
        workspaceSlug={projectSlug ?? undefined}
      />
    </div>
  );
}

// ── SimpleFileViewer ──────────────────────────────────────────────────────────

function SimpleFileViewer({ slug, node }: { slug: string; node: WorkspaceFileNode }) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const cat = getFileCategory(node.mime ?? "application/octet-stream", node.name);
    if (cat !== "text") return;
    setLoading(true);
    setContent(null);
    api.getWorkspaceFile(slug, node.path)
      .then((res) => setContent(res.content))
      .catch(() => setContent("Error loading file."))
      .finally(() => setLoading(false));
  }, [slug, node.path, node.mime, node.name]);

  const cat = getFileCategory(node.mime ?? "application/octet-stream", node.name);

  if (cat === "image") {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <img src={workspaceRawFileUrl(slug, node.path)} alt={node.name} className="max-h-full max-w-full rounded border border-border object-contain" />
      </div>
    );
  }

  if (cat === "video") {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <video src={workspaceRawFileUrl(slug, node.path)} controls className="max-h-full max-w-full rounded border border-border" />
      </div>
    );
  }

  if (cat === "binary") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-4 text-center text-xs text-muted-foreground/60">
        <File className="h-8 w-8 opacity-20" />
        <p>Binary file — no preview.</p>
        <a href={workspaceRawFileUrl(slug, node.path)} download={node.name} className="text-primary hover:underline">Download {node.name}</a>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (content !== null) {
    const lang = languageForFile(node.name);
    let html = content;
    try {
      html = lang && hljs.getLanguage(lang)
        ? hljs.highlight(content, { language: lang, ignoreIllegals: true }).value
        : hljs.highlightAuto(content).value;
    } catch { /* use raw content */ }

    return (
      <div className="spark-code-pane h-full overflow-auto">
        <div className="sticky top-0 z-10 flex h-6 items-center justify-between border-b border-border bg-background/85 px-3 text-[10px] text-muted-foreground backdrop-blur">
          <span className="truncate font-mono-ui">{node.path}</span>
          {lang && <span className="shrink-0 uppercase tracking-[0.12em]">{lang}</span>}
        </div>
        <pre className="hljs min-h-full overflow-visible px-4 py-3 font-mono-ui text-[0.72rem] leading-5">
          <code dangerouslySetInnerHTML={{ __html: html }} />
        </pre>
      </div>
    );
  }

  return null;
}

// ── WorkspaceRightPanel ───────────────────────────────────────────────────────

type RightTab = "files" | "terminal";

function WorkspaceRightPanel({
  slug,
  open,
  onToggle,
}: {
  slug: string;
  open: boolean;
  onToggle: () => void;
}) {
  const [activeTab, setActiveTab] = useState<RightTab>("files");
  const [selectedFile, setSelectedFile] = useState<WorkspaceFileNode | null>(null);

  // Reset selected file when project changes
  useEffect(() => { setSelectedFile(null); }, [slug]);

  if (!open) {
    return (
      <div className="spark-glass-panel flex w-9 shrink-0 flex-col items-center gap-2 border-l border-border py-2">
        <button
          type="button"
          title="Expand file panel"
          onClick={onToggle}
          className="rounded p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        <div className="h-px w-5 bg-border" />
        <button
          type="button"
          title="Files"
          onClick={() => { setActiveTab("files"); onToggle(); }}
          className={cn("rounded p-1.5 transition", activeTab === "files" ? "text-foreground" : "text-muted-foreground/40 hover:text-muted-foreground")}
        >
          <FileText className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          title="Terminal"
          onClick={() => { setActiveTab("terminal"); onToggle(); }}
          className={cn("rounded p-1.5 transition", activeTab === "terminal" ? "text-foreground" : "text-muted-foreground/40 hover:text-muted-foreground")}
        >
          <SquareTerminal className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div className="spark-glass-panel flex w-[320px] shrink-0 flex-col overflow-hidden border-l border-border">
      {/* Tab bar */}
      <div className="flex h-8 shrink-0 items-center border-b border-border">
        {(["files", "terminal"] as RightTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={cn(
              "flex h-8 items-center gap-1.5 border-r border-border px-3 text-[11px] capitalize transition",
              activeTab === tab
                ? "bg-background text-foreground"
                : "bg-card/50 text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            {tab === "files" ? <FileText className="h-3.5 w-3.5" /> : <SquareTerminal className="h-3.5 w-3.5" />}
            {tab}
          </button>
        ))}
        <button
          type="button"
          title="Collapse file panel"
          onClick={onToggle}
          className="ml-auto flex h-8 w-8 items-center justify-center text-muted-foreground transition hover:bg-secondary hover:text-foreground"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Tab content */}
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {activeTab === "files" ? (
          selectedFile ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              {/* Back to tree button */}
              <div className="flex shrink-0 items-center gap-2 border-b border-border px-2 py-1">
                <button
                  type="button"
                  className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-muted-foreground transition hover:bg-secondary hover:text-foreground"
                  onClick={() => setSelectedFile(null)}
                >
                  <ChevronLeft className="h-3 w-3" />
                  Files
                </button>
                <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground/70 font-mono-ui">
                  {selectedFile.name}
                </span>
              </div>
              <SimpleFileViewer slug={slug} node={selectedFile} />
            </div>
          ) : (
            <FileTreePane
              slug={slug}
              activePath={null}
              onOpenFile={setSelectedFile}
            />
          )
        ) : (
          <WorkspaceTerminalPanel slug={slug} />
        )}
      </div>
    </div>
  );
}

// ── ChatPage ──────────────────────────────────────────────────────────────────

export default function ChatPage() {
  // ── Data ──
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [loadingSessions, setLoadingSessions] = useState(false);

  // ── Navigation ──
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // null = nothing; "global" = new global thread; "{slug}" = new workspace thread
  const [composingFor, setComposingFor] = useState<"global" | string | null>(null);

  // ── Sidebar UI ──
  const [expandedProjects, setExpandedProjects] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem("spark-chat-expanded") ?? "[]") as string[]); }
    catch { return new Set<string>(); }
  });
  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<SessionInfo[] | null>(null);
  const [searching, setSearching] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Project creation ──
  const [creatingProject, setCreatingProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [savingProject, setSavingProject] = useState(false);

  // ── Right panel ──
  const [rightPanelOpen, setRightPanelOpen] = useState(() =>
    localStorage.getItem("spark-chat-right-panel") !== "false"
  );

  // ── Bulk select / delete ──
  const [selectMode, setSelectMode] = useState(false);
  const [selectedBulkIds, setSelectedBulkIds] = useState<Set<string>>(new Set());
  const [bulkDeleting, setBulkDeleting] = useState(false);

  // ── Mobile sidebar drawer ──
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  // ── Unread session notifications ──
  const [unreadSessionIds, setUnreadSessionIds] = useState<Set<string>>(getUnreadSessionIds);
  useEffect(() => subscribeToUnreadSessions(() => setUnreadSessionIds(getUnreadSessionIds())), []);
  // Track last-known message count per session so we can detect new messages via SSE
  const lastMessageCountRef = useRef<Map<string, number>>(new Map());

  // ── Derived ──
  const sessionsBySlug = useMemo(() => {
    const map = new Map<string, SessionInfo[]>();
    for (const s of sessions) {
      const slug = slugFromSource(s.source);
      if (!slug) continue;
      const list = map.get(slug) ?? [];
      list.push(s);
      map.set(slug, list);
    }
    return map;
  }, [sessions]);

  const selectedSession = useMemo(
    () => sessions.find((s) => s.id === selectedId) ?? null,
    [sessions, selectedId],
  );

  const activeProjectSlug = useMemo(
    () => slugFromSource(selectedSession?.source ?? null),
    [selectedSession],
  );

  const composingProjectName = useMemo(() => {
    if (!composingFor || composingFor === "global") return null;
    return projects.find((p) => p.slug === composingFor)?.name ?? composingFor;
  }, [composingFor, projects]);

  // Sessions to show in sidebar (search or full list)
  const displayedSessions = searchResults ?? sessions;
  const displayedGlobal = useMemo(
    () => displayedSessions.filter((s) => !slugFromSource(s.source)),
    [displayedSessions],
  );
  const displayedBySlug = useMemo(() => {
    const map = new Map<string, SessionInfo[]>();
    for (const s of displayedSessions) {
      const slug = slugFromSource(s.source);
      if (!slug) continue;
      const list = map.get(slug) ?? [];
      list.push(s);
      map.set(slug, list);
    }
    return map;
  }, [displayedSessions]);

  // ── Load data ──
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

  const loadSessions = useCallback(async () => {
    setLoadingSessions(true);
    try {
      const res = await api.getSessions(500, 0);
      // Seed known message counts — any SSE update that exceeds these is "new"
      const counts = new Map<string, number>();
      res.sessions.forEach((s) => counts.set(s.id, s.message_count ?? 0));
      lastMessageCountRef.current = counts;
      setSessions(res.sessions);
    } catch (e) {
      console.error("Load sessions failed", e);
    } finally {
      setLoadingSessions(false);
    }
  }, []);

  useEffect(() => {
    void loadProjects();
    void loadSessions();
  }, [loadProjects, loadSessions]);

  // ── Real-time updates ──
  useEventBus((env: SparkEventEnvelope) => {
    if (env.topic !== "sessions.changed") return;
    const data = env.data as { action?: string; session_id?: string; session?: SessionInfo };
    const sid = data.session_id ?? "";

    if (data.action === "deleted" && sid) {
      dismissSessionNotification(sid);
      setSessions((prev) => prev.filter((s) => s.id !== sid));
      if (selectedId === sid) { setSelectedId(null); setComposingFor(null); }
      return;
    }

    if (data.session) {
      const row = data.session;

      // Detect new messages on a thread the user isn't currently viewing →
      // show an unread notification dot + bell entry.
      if (row.id !== selectedId && (row.message_count ?? 0) > 0) {
        const lastCount = lastMessageCountRef.current.get(row.id) ?? 0;
        const newCount = row.message_count ?? 0;
        if (newCount > lastCount) {
          addSessionNotification(
            row.id,
            threadTitle(row) || "Untitled thread",
            row.preview ?? null,
          );
        }
        lastMessageCountRef.current.set(row.id, Math.max(lastCount, newCount));
      }

      setSessions((prev) => {
        const idx = prev.findIndex((s) => s.id === row.id);
        if (idx >= 0) {
          const next = [...prev];
          const existing = next[idx];
          next[idx] = {
            ...existing,
            ...row,
            preview: row.preview?.trim() ? row.preview : existing.preview,
            message_count: Math.max(row.message_count ?? 0, existing.message_count ?? 0),
            is_active: typeof row.is_active === "boolean" ? row.is_active : existing.is_active,
          };
          return next.sort((a, b) => b.last_active - a.last_active);
        }
        return [row, ...prev];
      });
    }
  });

  // ── Search ──
  useEffect(() => {
    if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
    if (!searchQ.trim()) { setSearchResults(null); setSearching(false); return; }

    // Client-side filter for short queries
    if (searchQ.trim().length < 3) {
      const q = searchQ.toLowerCase();
      setSearchResults(sessions.filter(
        (s) => threadTitle(s).toLowerCase().includes(q) || s.preview?.toLowerCase().includes(q),
      ));
      return;
    }

    // FTS5 search for longer queries
    setSearching(true);
    searchDebounceRef.current = setTimeout(async () => {
      try {
        const res = await api.searchSessions(searchQ.trim(), 100);
        setSearchResults(
          res.results
            .map((r) => sessions.find((s) => s.id === r.session_id))
            .filter((s): s is SessionInfo => Boolean(s)),
        );
      } catch {
        // Fall back to client-side filter
        const q = searchQ.toLowerCase();
        setSearchResults(sessions.filter(
          (s) => threadTitle(s).toLowerCase().includes(q) || s.preview?.toLowerCase().includes(q),
        ));
      } finally {
        setSearching(false);
      }
    }, 300);
  }, [searchQ, sessions]);

  // Cmd+K focuses search
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

  // ── Actions ──
  const toggleExpanded = (slug: string) => {
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug); else next.add(slug);
      localStorage.setItem("spark-chat-expanded", JSON.stringify([...next]));
      return next;
    });
  };

  const toggleRightPanel = () => {
    setRightPanelOpen((v) => {
      const next = !v;
      localStorage.setItem("spark-chat-right-panel", String(next));
      return next;
    });
  };

  const handleSelectThread = (id: string) => {
    markSessionRead(id);
    // Sync lastMessageCountRef to the latest known count so we don't
    // immediately re-fire a notification for messages we just acknowledged.
    const session = sessions.find((s) => s.id === id);
    if (session?.message_count != null) {
      lastMessageCountRef.current.set(id, session.message_count);
    }
    setSelectedId(id);
    setComposingFor(null);
    setMobileSidebarOpen(false); // close mobile drawer on selection
  };

  const handleDeleteThread = async (id: string) => {
    setSessions((prev) => prev.filter((s) => s.id !== id));
    if (selectedId === id) setSelectedId(null);
    try { await api.deleteSession(id); }
    catch { void loadSessions(); }
  };

  const handleNewGlobalChat = () => {
    setSelectedId(null);
    setComposingFor("global");
  };

  const handleNewProjectThread = (slug: string) => {
    setSelectedId(null);
    setComposingFor(slug);
    // Auto-expand the project folder
    setExpandedProjects((prev) => {
      const next = new Set(prev);
      next.add(slug);
      localStorage.setItem("spark-chat-expanded", JSON.stringify([...next]));
      return next;
    });
  };

  const [pendingInitialMessage, setPendingInitialMessage] = useState<string | null>(null);

  const handleThreadCreated = (sessionId: string, initialMessage: string) => {
    setPendingInitialMessage(initialMessage);
    setComposingFor(null);
    setSelectedId(sessionId);
    void loadSessions();
  };

  const handleCreateProject = async () => {
    const name = newProjectName.trim();
    if (!name) return;
    setSavingProject(true);
    try {
      const res = await api.createWorkspaceProject(name);
      await loadProjects();
      setNewProjectName("");
      setCreatingProject(false);
      // Auto-expand the new project
      setExpandedProjects((prev) => {
        const next = new Set(prev);
        next.add(res.slug);
        localStorage.setItem("spark-chat-expanded", JSON.stringify([...next]));
        return next;
      });
    } finally {
      setSavingProject(false);
    }
  };

  const handleDeleteProject = async (slug: string) => {
    try {
      await api.deleteWorkspaceProject(slug);
      await loadProjects();
      // Clear any selection that belonged to this project
      if (activeProjectSlug === slug) setSelectedId(null);
      if (composingFor === slug) setComposingFor(null);
    } catch (e) {
      console.error("Delete project failed", e);
    }
  };

  // ── Bulk delete actions ──
  const handleToggleBulkSelect = (id: string) => {
    setSelectedBulkIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleBulkDelete = async () => {
    if (!selectedBulkIds.size || bulkDeleting) return;
    setBulkDeleting(true);
    const ids = Array.from(selectedBulkIds);
    // Optimistic remove
    setSessions((prev) => prev.filter((s) => !selectedBulkIds.has(s.id)));
    if (selectedId && selectedBulkIds.has(selectedId)) setSelectedId(null);
    await Promise.allSettled(ids.map((id) => api.deleteSession(id)));
    setSelectedBulkIds(new Set());
    setSelectMode(false);
    setBulkDeleting(false);
  };

  const handleCleanUpEmpty = () => {
    const emptyIds = new Set(sessions.filter((s) => (s.message_count ?? 0) === 0).map((s) => s.id));
    setSelectedBulkIds(emptyIds);
    setSelectMode(true);
  };

  const exitSelectMode = () => {
    setSelectMode(false);
    setSelectedBulkIds(new Set());
  };

  // ── Render ──
  return (
    <div className="flex h-full max-h-screen min-h-0 overflow-hidden border-t border-border bg-card/70 backdrop-blur-xl">

      {/* ── Mobile sidebar overlay backdrop ── */}
      {mobileSidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-background/60 backdrop-blur-sm md:hidden"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      {/* ── Sidebar ── */}
      <aside className={cn(
        "flex w-[260px] shrink-0 flex-col overflow-hidden border-r border-border bg-card/50",
        // Desktop: always visible
        "md:relative md:flex md:translate-x-0",
        // Mobile: absolute overlay drawer
        "fixed inset-y-0 left-0 z-50 md:static",
        mobileSidebarOpen ? "flex" : "hidden md:flex",
      )}>

        {/* Toolbar */}
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-3">
          <Button
            size="sm"
            className="h-8 flex-1 gap-1.5 text-xs"
            onClick={handleNewGlobalChat}
            disabled={selectMode}
          >
            <Plus className="h-3.5 w-3.5" />
            New chat
          </Button>
          <button
            type="button"
            title="Select threads"
            className={cn(
              "grid h-8 w-8 shrink-0 place-items-center rounded-sm border transition",
              selectMode
                ? "border-primary/50 bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
            onClick={() => selectMode ? exitSelectMode() : setSelectMode(true)}
          >
            <CheckSquare className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="Clean up empty threads"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-sm border border-border text-muted-foreground transition hover:bg-secondary hover:text-foreground"
            onClick={handleCleanUpEmpty}
          >
            <Brush className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="Search (⌘K)"
            className="grid h-8 w-8 shrink-0 place-items-center rounded-sm border border-border text-muted-foreground transition hover:bg-secondary hover:text-foreground"
            onClick={() => searchInputRef.current?.focus()}
          >
            <Search className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Search */}
        <div className="shrink-0 border-b border-border px-3 py-2">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/60" />
            <Input
              ref={searchInputRef}
              className="h-7 pl-7 pr-8 text-[12px]"
              placeholder="Search threads…"
              value={searchQ}
              onChange={(e) => setSearchQ(e.target.value)}
            />
            {searching && <Loader2 className="absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 animate-spin text-muted-foreground/60" />}
            {searchQ && !searching && (
              <button
                type="button"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/60 hover:text-foreground"
                onClick={() => setSearchQ("")}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>

        {/* Scrollable list */}
        <div className="min-h-0 flex-1 overflow-y-auto">

          {/* Projects section */}
          <div className="py-2">
            <div className="flex items-center justify-between px-3 pb-1">
              <span className="text-[10px] uppercase tracking-widest text-muted-foreground/50">
                Projects
              </span>
              <div className="flex items-center gap-0.5">
                {loadingProjects && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/40" />}
                <button
                  type="button"
                  title="New project"
                  className="rounded p-0.5 text-muted-foreground/50 transition hover:bg-secondary hover:text-foreground"
                  onClick={() => setCreatingProject(true)}
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* New project form */}
            {creatingProject && (
              <div className="mx-2 mb-2 flex flex-col gap-1.5 rounded-sm border border-border bg-background/60 p-2">
                <Input
                  autoFocus
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  placeholder="Project name"
                  className="h-7 text-xs"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleCreateProject();
                    if (e.key === "Escape") { setCreatingProject(false); setNewProjectName(""); }
                  }}
                />
                <div className="flex gap-1">
                  <Button size="sm" className="h-6 flex-1 text-xs" onClick={() => void handleCreateProject()} disabled={savingProject}>
                    {savingProject ? <Loader2 className="h-3 w-3 animate-spin" /> : "Create"}
                  </Button>
                  <Button size="sm" variant="ghost" className="h-6 w-6 p-0" onClick={() => { setCreatingProject(false); setNewProjectName(""); }}>
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            )}

            {!loadingProjects && projects.length === 0 && !creatingProject && (
              <p className="px-3 py-2 text-[11px] text-muted-foreground/40">
                No projects yet. Click + to create one.
              </p>
            )}

            {projects.map((project) => (
              <ProjectFolder
                key={project.slug}
                project={project}
                threads={
                  searchResults
                    ? (displayedBySlug.get(project.slug) ?? [])
                    : (sessionsBySlug.get(project.slug) ?? [])
                }
                isExpanded={expandedProjects.has(project.slug)}
                selectedId={selectedId}
                onToggle={() => toggleExpanded(project.slug)}
                onSelect={(id) => handleSelectThread(id)}
                onDelete={handleDeleteThread}
                onNewThread={handleNewProjectThread}
                onDeleteProject={handleDeleteProject}
                selectMode={selectMode}
                selectedBulkIds={selectedBulkIds}
                onToggleSelect={handleToggleBulkSelect}
                unreadSessionIds={unreadSessionIds}
              />
            ))}
          </div>

          {/* Chats section */}
          {(displayedGlobal.length > 0 || !searchResults) && (
            <div className="border-t border-border py-2">
              <div className="flex items-center justify-between px-3 pb-1">
                <span className="text-[10px] uppercase tracking-widest text-muted-foreground/50">
                  Chats
                </span>
                {loadingSessions && !sessions.length && (
                  <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/40" />
                )}
              </div>

              {displayedGlobal.length === 0 && !loadingSessions && (
                <p className="px-3 py-2 text-[11px] text-muted-foreground/40">
                  {searchQ ? "No matching chats" : "No chats yet"}
                </p>
              )}

              {displayedGlobal.map((s) => (
                <CompactThreadRow
                  key={s.id}
                  session={s}
                  active={selectedId === s.id}
                  selectMode={selectMode}
                  selected={selectedBulkIds.has(s.id)}
                  unread={unreadSessionIds.has(s.id)}
                  onOpen={() => handleSelectThread(s.id)}
                  onDelete={() => void handleDeleteThread(s.id)}
                  onToggleSelect={() => handleToggleBulkSelect(s.id)}
                />
              ))}
            </div>
          )}

          {/* Empty search state */}
          {searchResults !== null && displayedSessions.length === 0 && (
            <div className="flex flex-col items-center gap-2 px-4 py-8 text-center text-muted-foreground">
              <Bot className="h-8 w-8 opacity-20" />
              <p className="text-xs">No results for "{searchQ}"</p>
            </div>
          )}
        </div>

        {/* Bulk action footer */}
        {selectMode && (
          <div className="flex shrink-0 items-center gap-2 border-t border-border bg-background/80 px-3 py-2.5">
            <span className="flex-1 text-xs text-muted-foreground">
              {selectedBulkIds.size} selected
            </span>
            <button
              type="button"
              disabled={!selectedBulkIds.size || bulkDeleting}
              className="inline-flex h-7 items-center gap-1.5 rounded-sm border border-destructive/40 bg-destructive/10 px-2.5 text-xs font-medium text-destructive transition hover:bg-destructive/20 disabled:opacity-50"
              onClick={() => void handleBulkDelete()}
            >
              {bulkDeleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
              Delete
            </button>
            <button
              type="button"
              className="inline-flex h-7 items-center rounded-sm border border-border px-2.5 text-xs text-muted-foreground transition hover:bg-secondary hover:text-foreground"
              onClick={exitSelectMode}
            >
              Cancel
            </button>
          </div>
        )}
      </aside>

      {/* ── Main area ── */}
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">

        {/* Content: compose or chat */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {composingFor !== null ? (
            <NewThreadCompose
              projectSlug={composingFor === "global" ? null : composingFor}
              projectName={composingProjectName}
              onCreated={handleThreadCreated}
              onCancel={() => setComposingFor(null)}
            />
          ) : selectedId ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              {/* Thread header */}
              <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border bg-background/70 px-4 py-2">
                <div className="flex items-center gap-2 min-w-0">
                  <button
                    type="button"
                    className="grid h-7 w-7 shrink-0 place-items-center rounded-sm text-muted-foreground transition hover:bg-secondary hover:text-foreground md:hidden"
                    onClick={() => setMobileSidebarOpen(true)}
                  >
                    <Menu className="h-4 w-4" />
                  </button>
                  <p className="min-w-0 truncate text-sm font-medium">
                    {selectedSession ? threadTitle(selectedSession) : "Thread"}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {activeProjectSlug && (
                    <button
                      type="button"
                      title={rightPanelOpen ? "Hide files" : "Show files"}
                      onClick={toggleRightPanel}
                      className={cn(
                        "grid h-7 w-7 place-items-center rounded-sm border transition",
                        rightPanelOpen
                          ? "border-primary/50 bg-primary/10 text-primary"
                          : "border-border text-muted-foreground hover:bg-secondary hover:text-foreground",
                      )}
                    >
                      <PanelRight className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>
              <ChatPanel
                sessionId={selectedId}
                sessionTitle={selectedSession ? threadTitle(selectedSession) : null}
                workspaceSlug={activeProjectSlug ?? undefined}
                initialMessage={pendingInitialMessage ?? undefined}
                onBack={() => setSelectedId(null)}
                onSessionCreated={(id) => setSelectedId(id)}
                onSessionUpdated={() => setPendingInitialMessage(null)}
                className="min-h-0 flex-1"
              />
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center px-6 text-center text-muted-foreground">
              {/* Mobile hamburger — visible when sidebar is closed */}
              <button
                type="button"
                className="absolute left-4 top-4 grid h-8 w-8 place-items-center rounded-sm border border-border text-muted-foreground transition hover:bg-secondary hover:text-foreground md:hidden"
                onClick={() => setMobileSidebarOpen(true)}
              >
                <Menu className="h-4 w-4" />
              </button>
              <MessageSquare className="mb-4 h-12 w-12 opacity-20" />
              <p className="text-sm font-medium text-foreground">Select a conversation</p>
              <p className="mt-1 max-w-sm text-xs opacity-75">
                Pick a thread from the sidebar, or click <span className="text-foreground">New chat</span> to start one.
              </p>
            </div>
          )}
        </div>

        {/* Right panel — only when a workspace thread is selected; hidden on mobile */}
        {activeProjectSlug && (
          <div className="hidden md:flex">
            <WorkspaceRightPanel
              slug={activeProjectSlug}
              open={rightPanelOpen}
              onToggle={toggleRightPanel}
            />
          </div>
        )}
      </div>
    </div>
  );
}
