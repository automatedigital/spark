import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  Copy,
  File,
  FileText,
  GitBranch,
  Globe,
  GripVertical,
  Loader2,
  MessageSquare,
  PanelRightClose,
  PanelRightOpen,
  SquareTerminal,
  X,
} from "lucide-react";
import hljs from "highlight.js";
import { api, workspaceRawFileUrl } from "@/lib/api";
import type { WorkspaceFileNode } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { ChatPanel } from "@/components/ChatPanel";
import { BrandLogo } from "@/components/BrandLogo";
import { PromptBar } from "@/components/chat/PromptBar";
import { useEventBus } from "@/hooks/useEventBus";
import type { SparkEventEnvelope } from "@/hooks/useEventBus";
import { threadTitle } from "@/components/chat/ThreadRow";
import { TypeOnTitle } from "@/components/chat/TypeOnTitle";
import { FileTreePane } from "@/components/workspace/FileTreePane";
import { getFileCategory } from "@/lib/fileCategory";
import { WorkspaceTerminalPanel } from "@/components/workspace/WorkspaceTerminalPanel";
import { WorkspaceChangesPanel } from "@/components/workspace/WorkspaceChangesPanel";
import { WorkspacePreviewPanel } from "@/components/workspace/WorkspacePreviewPanel";
import { previewAutoOpenEnabled } from "@/lib/previewPrefs";
import { useSessionStore, slugFromSource } from "@/lib/sessionStore";

// ── Helpers ───────────────────────────────────────────────────────────────────

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

// ── Resize divider ─────────────────────────────────────────────────────────────

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
      className="group relative hidden w-2 shrink-0 cursor-col-resize items-center justify-center md:flex"
    >
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border transition-colors group-hover:bg-primary/50 group-active:bg-primary/70" />
      <GripVertical className="relative z-10 h-4 w-4 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/50 group-active:text-primary/70" />
    </div>
  );
}

// ── NewSessionHero (Phase 2) ──────────────────────────────────────────────────

function NewSessionHero({
  onCreated,
}: {
  onCreated: (sessionId: string, initialMessage: string) => void;
}) {
  const [msg, setMsg] = useState("");
  const [starting, setStarting] = useState(false);

  const handleSend = async () => {
    const text = msg.trim();
    if (!text || starting) return;
    setStarting(true);
    try {
      const res = await api.postConversation(text);
      onCreated(res.session_id, text);
    } catch (e) {
      console.error("Failed to start conversation", e);
      setStarting(false);
    }
  };

  // Upload into the shared chat workspace (no project yet on the hero) and
  // insert @files/<name> references into the draft so the new turn can read
  // them. Mirrors NewThreadCompose.handleUpload.
  const handleUpload = async (files: File[]) => {
    const res = await api.uploadChatFiles(files);
    const refs = res.saved.map((f) => `@${f.path}`).join(" ");
    setMsg((prev) => {
      const prefix = prev.trimEnd();
      return prefix ? `${prefix}\n${refs} ` : `${refs} `;
    });
  };

  const [isDragOver, setIsDragOver] = useState(false);
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) void handleUpload(files);
  };

  return (
    <div
      className="relative flex min-h-0 flex-1 flex-col overflow-hidden"
      onDragOver={(e) => {
        e.preventDefault();
        if (e.dataTransfer.types.includes("Files")) setIsDragOver(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        setIsDragOver(false);
      }}
      onDrop={handleDrop}
    >
      {isDragOver && (
        <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center rounded-lg border-2 border-dashed border-primary/50 bg-background/70 text-sm font-medium text-foreground">
          Drop files to attach
        </div>
      )}
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-6 text-center">
        <div className="flex items-center gap-4">
          <BrandLogo className="size-16 sm:size-20 md:size-24" />
          <h1 className="text-5xl font-semibold text-foreground/90 sm:text-6xl md:text-7xl">
            Spark
          </h1>
        </div>
        <p className="mt-5 max-w-md text-sm leading-relaxed text-muted-foreground/70">
          Type a task, question, or snippet…
        </p>
      </div>
      <div className="mx-auto w-full max-w-2xl shrink-0 px-4 pb-6 sm:pb-8">
        <PromptBar
          input={msg}
          setInput={setMsg}
          streaming={false}
          onSend={() => void handleSend()}
          onStop={() => {}}
          onUploadFiles={handleUpload}
          disabled={starting}
          placeholder="Start with a goal"
        />
      </div>
    </div>
  );
}

// ── NewThreadCompose (project workspace threads) ──────────────────────────────

function NewThreadCompose({
  projectSlug,
  projectName,
  onCreated,
  onCancel,
}: {
  projectSlug: string;
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
      const res = await api.startWorkspaceConversation(projectSlug, text);
      onCreated(res.session_id, text);
    } catch (e) {
      console.error("Failed to start conversation", e);
      setStarting(false);
    }
  };

  const handleUpload = async (files: File[]) => {
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
          New thread in {projectName ?? projectSlug}
        </p>
        <Button size="sm" variant="ghost" className="h-7 gap-1.5 px-2 text-xs" onClick={onCancel}>
          <X className="h-3.5 w-3.5" />
          Cancel
        </Button>
      </div>
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center text-muted-foreground">
        <MessageSquare className="mb-4 h-12 w-12 opacity-20" />
        <p className="text-sm font-medium text-foreground">Start a project conversation</p>
        <p className="mt-1 max-w-sm text-xs opacity-75">
          Spark has context of the workspace files for this project.
        </p>
      </div>
      <PromptBar
        input={msg}
        setInput={setMsg}
        streaming={false}
        onSend={() => void handleSend()}
        onStop={() => {}}
        onUploadFiles={handleUpload}
        disabled={starting}
        workspaceSlug={projectSlug}
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

    const lineCount = content.split("\n").length;

    return (
      <div className="spark-code-pane h-full overflow-auto">
        <div className="sticky top-0 z-10 flex h-6 items-center justify-between gap-2 border-b border-border bg-background/85 px-3 text-[10px] text-muted-foreground backdrop-blur">
          <span className="truncate font-mono-ui">{node.path}</span>
          <div className="flex shrink-0 items-center gap-2">
            {lang && <span className="uppercase tracking-[0.12em]">{lang}</span>}
            <CopyPathButton path={node.path} />
          </div>
        </div>
        <div className="flex min-h-full font-mono-ui text-[0.72rem] leading-5">
          <pre
            aria-hidden
            className="shrink-0 select-none border-r border-border/60 px-2 py-3 text-right text-muted-foreground/35"
          >
            {Array.from({ length: lineCount }, (_, i) => i + 1).join("\n")}
          </pre>
          <pre className="hljs min-h-full flex-1 overflow-visible px-4 py-3">
            <code dangerouslySetInnerHTML={{ __html: html }} />
          </pre>
        </div>
      </div>
    );
  }

  return null;
}

function CopyPathButton({ path }: { path: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      title="Copy path"
      className="flex items-center gap-1 rounded px-1 py-0.5 transition hover:bg-secondary hover:text-foreground"
      onClick={() => {
        void navigator.clipboard.writeText(path).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1200);
        });
      }}
    >
      {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
    </button>
  );
}

// ── WorkspaceRightPanel ───────────────────────────────────────────────────────

type RightTab = "preview" | "terminal" | "files" | "changes";

type RightTabMeta = {
  id: RightTab;
  label: string;
  shortcut: string;
  Icon: typeof FileText;
};

// Dropdown order mirrors Claude desktop's panel switcher (Preview first).
const RIGHT_TAB_META: RightTabMeta[] = [
  { id: "preview", label: "Preview", shortcut: "⇧⌘P", Icon: Globe },
  { id: "terminal", label: "Terminal", shortcut: "⌃`", Icon: SquareTerminal },
  { id: "files", label: "Files", shortcut: "⇧⌘F", Icon: FileText },
  { id: "changes", label: "Changes", shortcut: "⇧⌘D", Icon: GitBranch },
];

function rightTabMeta(tab: RightTab): RightTabMeta {
  return RIGHT_TAB_META.find((m) => m.id === tab) ?? RIGHT_TAB_META[0];
}

const RIGHT_TAB_KEY_PREFIX = "spark-chat-right-tab:";

function loadRightTab(slug: string): RightTab {
  const saved = localStorage.getItem(RIGHT_TAB_KEY_PREFIX + slug);
  return RIGHT_TAB_META.some((m) => m.id === saved) ? (saved as RightTab) : "files";
}

function saveRightTab(slug: string, tab: RightTab) {
  localStorage.setItem(RIGHT_TAB_KEY_PREFIX + slug, tab);
}

// Compact tab switcher: current tab + chevron, dropdown lists every pane with
// its keyboard shortcut (Claude desktop OPTIONS style).
function RightPanelSwitcher({
  slug,
  activeTab,
  onSelect,
}: {
  slug: string;
  activeTab: RightTab;
  onSelect: (tab: RightTab) => void;
}) {
  const [open, setOpen] = useState(false);
  const [gitTotals, setGitTotals] = useState<{ adds: number; dels: number } | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const active = rightTabMeta(activeTab);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  // Fetch the change summary lazily when the menu opens (codex OPTIONS style).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void api.getWorkspaceGitStatus(slug)
      .then((s) => { if (!cancelled) setGitTotals(s.is_repo ? { adds: s.total_adds, dels: s.total_dels } : null); })
      .catch(() => { if (!cancelled) setGitTotals(null); });
    return () => { cancelled = true; };
  }, [open, slug]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex h-7 items-center gap-1.5 rounded px-2 text-[11px] font-medium text-foreground transition hover:bg-secondary"
      >
        <active.Icon className="h-3.5 w-3.5" />
        {active.label}
        <ChevronDown className={cn("h-3 w-3 text-muted-foreground transition", open && "rotate-180")} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 top-8 z-30 min-w-[180px] overflow-hidden rounded-md border border-border bg-popover py-1 shadow-lg"
        >
          {RIGHT_TAB_META.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="menuitem"
              onClick={() => { onSelect(tab.id); setOpen(false); }}
              className={cn(
                "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-[11px] transition",
                tab.id === activeTab
                  ? "bg-secondary text-foreground"
                  : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
              )}
            >
              <tab.Icon className="h-3.5 w-3.5 shrink-0" />
              <span className="flex-1">{tab.label}</span>
              {tab.id === "changes" && gitTotals && (gitTotals.adds > 0 || gitTotals.dels > 0) && (
                <span className="font-mono-ui text-[10px]">
                  <span className="text-emerald-400/80">+{gitTotals.adds}</span>{" "}
                  <span className="text-red-400/80">-{gitTotals.dels}</span>
                </span>
              )}
              <span className="font-mono-ui text-[10px] text-muted-foreground/60">{tab.shortcut}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function WorkspaceRightPanel({
  slug,
  open,
  onToggle,
  width,
  activeTab,
  onSelectTab,
}: {
  slug: string;
  open: boolean;
  onToggle: () => void;
  width: number;
  activeTab: RightTab;
  onSelectTab: (tab: RightTab) => void;
}) {
  const [selectedFile, setSelectedFile] = useState<WorkspaceFileNode | null>(null);

  // Reset selected file when project changes
  useEffect(() => { setSelectedFile(null); }, [slug]);

  // The panel keeps all panes mounted whether open or collapsed, so the terminal
  // shell and preview survive both tab switches AND collapse. When collapsed we
  // render a narrow rail and hide the pane stack via CSS.
  return (
    <div
      className={cn(
        "spark-glass-panel flex shrink-0 flex-col overflow-hidden border-l border-border",
        !open && "items-center",
      )}
      style={{ width: open ? width : 36 }}
    >
      {open ? (
        /* Header: tab switcher + collapse */
        <div className="flex h-8 w-full shrink-0 items-center gap-1 border-b border-border px-1.5">
          <RightPanelSwitcher slug={slug} activeTab={activeTab} onSelect={onSelectTab} />
          <button
            type="button"
            title="Collapse panel"
            onClick={onToggle}
            className="ml-auto flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition hover:bg-secondary hover:text-foreground"
          >
            <PanelRightClose className="h-4 w-4" />
          </button>
        </div>
      ) : (
        /* Collapsed rail */
        <div className="flex flex-col items-center gap-2 py-2">
          <button
            type="button"
            title="Show panel"
            onClick={onToggle}
            className="rounded p-1.5 text-muted-foreground/40 transition hover:text-muted-foreground"
          >
            <PanelRightOpen className="h-4 w-4" />
          </button>
          <div className="h-px w-4 bg-border" />
          {RIGHT_TAB_META.map(({ id, label, Icon }) => (
            <button
              key={id}
              type="button"
              title={label}
              onClick={() => { onSelectTab(id); onToggle(); }}
              className={cn("rounded p-1.5 transition", activeTab === id ? "text-foreground" : "text-muted-foreground/40 hover:text-muted-foreground")}
            >
              <Icon className="h-3.5 w-3.5" />
            </button>
          ))}
        </div>
      )}

      {/* Tab content — all panes stay mounted so the terminal shell and preview
          state survive tab switches and collapse; hidden panes are CSS-hidden. */}
      <div className={cn("relative flex w-full min-h-0 flex-1 flex-col overflow-hidden", !open && "hidden")}>
        <div className={cn("absolute inset-0 flex min-h-0 flex-col overflow-hidden", activeTab !== "files" && "hidden")}>
          {selectedFile ? (
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
          )}
        </div>
        <div className={cn("absolute inset-0 flex min-h-0 flex-col overflow-hidden", activeTab !== "terminal" && "hidden")}>
          <WorkspaceTerminalPanel slug={slug} />
        </div>
        <div className={cn("absolute inset-0 flex min-h-0 flex-col overflow-hidden", activeTab !== "preview" && "hidden")}>
          <WorkspacePreviewPanel slug={slug} visible={open && activeTab === "preview"} />
        </div>
        <div className={cn("absolute inset-0 flex min-h-0 flex-col overflow-hidden", activeTab !== "changes" && "hidden")}>
          <WorkspaceChangesPanel slug={slug} />
        </div>
      </div>
    </div>
  );
}

// ── ChatPage ──────────────────────────────────────────────────────────────────
//
// The session list / search / pinned sidebar now lives in the global sidebar
// (App.tsx + lib/sessionStore). ChatPage is the thread view only: the
// new-session hero, the project compose flow, ChatPanel and the workspace
// right panel.

export default function ChatPage() {
  const {
    projects,
    selectedId,
    selectedSession,
    composingFor,
    cancelCompose,
    selectSession,
    threadCreated,
    pendingInitialMessage,
    clearPendingInitialMessage,
  } = useSessionStore();

  // ── Right panel ──
  const [rightPanelOpen, setRightPanelOpen] = useState(() =>
    localStorage.getItem("spark-chat-right-panel") !== "false"
  );
  const [rightTab, setRightTab] = useState<RightTab>("files");
  const [rightPanelWidth, setRightPanelWidth] = useState(() => {
    const saved = localStorage.getItem("spark-chat-right-panel-width");
    return saved ? Math.max(240, parseInt(saved, 10)) : 320;
  });

  // ── Derived ──
  const activeProjectSlug = useMemo(
    () => slugFromSource(selectedSession?.source ?? null),
    [selectedSession],
  );
  const activeWorkspaceSlug = activeProjectSlug ?? composingFor;

  const composingProjectName = useMemo(() => {
    if (!composingFor) return null;
    return projects.find((p) => p.slug === composingFor)?.name ?? composingFor;
  }, [composingFor, projects]);

  // Load the per-workspace saved tab when the active workspace changes.
  useEffect(() => {
    if (activeWorkspaceSlug) setRightTab(loadRightTab(activeWorkspaceSlug));
  }, [activeWorkspaceSlug]);

  const selectRightTab = useCallback((tab: RightTab) => {
    setRightTab(tab);
    if (activeWorkspaceSlug) saveRightTab(activeWorkspaceSlug, tab);
  }, [activeWorkspaceSlug]);

  // ── Real-time updates ──
  useEventBus((env: SparkEventEnvelope) => {
    if (env.topic !== "workspace.preview.ready") return;
    const data = env.data as { slug?: string; url?: string | null };
    if (data.slug && data.slug === activeWorkspaceSlug && data.url && previewAutoOpenEnabled()) {
      setRightPanelOpen(true);
      localStorage.setItem("spark-chat-right-panel", "true");
      selectRightTab("preview");
    }
  });

  const toggleRightPanel = () => {
    setRightPanelOpen((v) => {
      const next = !v;
      localStorage.setItem("spark-chat-right-panel", String(next));
      return next;
    });
  };

  // Keyboard shortcuts to open/switch panel tabs (mirrors Claude desktop).
  useEffect(() => {
    if (!activeWorkspaceSlug) return;
    const onKey = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      let tab: RightTab | null = null;
      if (mod && e.shiftKey && e.key.toLowerCase() === "p") tab = "preview";
      else if (mod && e.shiftKey && e.key.toLowerCase() === "f") tab = "files";
      else if (mod && e.shiftKey && e.key.toLowerCase() === "d") tab = "changes";
      else if (e.ctrlKey && e.key === "`") tab = "terminal";
      if (!tab) return;
      e.preventDefault();
      setRightPanelOpen(true);
      localStorage.setItem("spark-chat-right-panel", "true");
      selectRightTab(tab);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [activeWorkspaceSlug, selectRightTab]);

  const handleRightPanelDrag = useCallback((delta: number) => {
    setRightPanelWidth((width) => {
      const next = Math.max(240, Math.min(720, width - delta));
      localStorage.setItem("spark-chat-right-panel-width", String(next));
      return next;
    });
  }, []);

  // ── Render ──
  return (
    <div className="flex h-full max-h-screen min-h-0 overflow-hidden border-t border-border bg-card/70 backdrop-blur-xl">
      {/* ── Main area ── */}
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">

        {/* Content: compose, chat, or hero */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {composingFor !== null ? (
            <NewThreadCompose
              projectSlug={composingFor}
              projectName={composingProjectName}
              onCreated={threadCreated}
              onCancel={cancelCompose}
            />
          ) : selectedId ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              {/* Thread header */}
              <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border bg-background/70 px-4 py-2">
                <div className="flex items-center gap-2 min-w-0">
                  <TypeOnTitle
                    text={selectedSession ? threadTitle(selectedSession) : "Thread"}
                    className="min-w-0 truncate text-sm font-medium"
                  />
                </div>
                <div className="flex shrink-0 items-center gap-2" />
              </div>
              <ChatPanel
                sessionId={selectedId}
                sessionTitle={selectedSession ? threadTitle(selectedSession) : null}
                workspaceSlug={activeProjectSlug ?? undefined}
                initialMessage={pendingInitialMessage ?? undefined}
                onBack={() => selectSession(null)}
                onSessionCreated={(id) => selectSession(id)}
                onSessionUpdated={clearPendingInitialMessage}
                className="min-h-0 flex-1"
              />
            </div>
          ) : (
            <NewSessionHero onCreated={threadCreated} />
          )}
        </div>

        {/* Right panel — only when a workspace thread is selected; hidden on mobile */}
        {activeWorkspaceSlug && (
          <div className="hidden md:flex">
            {rightPanelOpen && <ResizeDivider onDrag={handleRightPanelDrag} />}
            <WorkspaceRightPanel
              slug={activeWorkspaceSlug}
              open={rightPanelOpen}
              onToggle={toggleRightPanel}
              width={rightPanelWidth}
              activeTab={rightTab}
              onSelectTab={selectRightTab}
            />
          </div>
        )}
      </div>
    </div>
  );
}
