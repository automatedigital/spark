import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  File,
  FileText,
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
import { PromptBar } from "@/components/chat/PromptBar";
import { useEventBus } from "@/hooks/useEventBus";
import type { SparkEventEnvelope } from "@/hooks/useEventBus";
import { threadTitle } from "@/components/chat/ThreadRow";
import { TypeOnTitle } from "@/components/chat/TypeOnTitle";
import { FileTreePane, getFileCategory } from "@/components/workspace/FileTreePane";
import { WorkspaceTerminalPanel } from "@/components/workspace/WorkspaceTerminalPanel";
import { WorkspacePreviewPanel } from "@/components/workspace/WorkspacePreviewPanel";
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

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-6 text-center">
        <div className="flex items-center gap-4">
          <picture>
            <source srcSet="/icon_small-light.png" media="(prefers-color-scheme: dark)" />
            <img
              src="/icon_small-dark.png"
              alt=""
              className="size-14 object-contain sm:size-16 md:size-20"
            />
          </picture>
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

type RightTab = "files" | "terminal" | "preview";

const RIGHT_TABS: RightTab[] = ["files", "terminal", "preview"];

function rightTabLabel(tab: RightTab): string {
  if (tab === "files") return "Files";
  if (tab === "terminal") return "Terminal";
  return "Browser";
}

function RightTabIcon({ tab }: { tab: RightTab }) {
  if (tab === "files") return <FileText className="h-3.5 w-3.5" />;
  if (tab === "terminal") return <SquareTerminal className="h-3.5 w-3.5" />;
  return <Globe className="h-3.5 w-3.5" />;
}

function WorkspaceRightPanel({
  slug,
  open,
  onToggle,
  width,
  forceTab,
}: {
  slug: string;
  open: boolean;
  onToggle: () => void;
  width: number;
  forceTab?: RightTab | null;
}) {
  const [activeTab, setActiveTab] = useState<RightTab>("files");
  const [selectedFile, setSelectedFile] = useState<WorkspaceFileNode | null>(null);

  // Reset selected file when project changes
  useEffect(() => { setSelectedFile(null); }, [slug]);
  useEffect(() => {
    if (forceTab) setActiveTab(forceTab);
  }, [forceTab]);

  if (!open) {
    return (
      <div className="spark-glass-panel flex w-9 shrink-0 flex-col items-center gap-2 border-l border-border py-2">
        <button
          type="button"
          title="Show files"
          onClick={onToggle}
          className="rounded p-1.5 text-muted-foreground/40 transition hover:text-muted-foreground"
        >
          <PanelRightOpen className="h-4 w-4" />
        </button>
        <div className="h-px w-4 bg-border" />
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
        <button
          type="button"
          title="Browser"
          onClick={() => { setActiveTab("preview"); onToggle(); }}
          className={cn("rounded p-1.5 transition", activeTab === "preview" ? "text-foreground" : "text-muted-foreground/40 hover:text-muted-foreground")}
        >
          <Globe className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return (
    <div
      className="spark-glass-panel flex shrink-0 flex-col overflow-hidden border-l border-border"
      style={{ width }}
    >
      {/* Tab bar */}
      <div
        className="flex h-8 shrink-0 items-center border-b border-border"
        role="tablist"
        aria-label="Project tools"
      >
        {RIGHT_TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            aria-label={rightTabLabel(tab)}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "flex h-8 items-center gap-1.5 border-r border-border px-3 text-[11px] capitalize transition",
              activeTab === tab
                ? "bg-background text-foreground"
                : "bg-card/50 text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            <RightTabIcon tab={tab} />
            {tab}
          </button>
        ))}
        <button
          type="button"
          title="Collapse file panel"
          onClick={onToggle}
          className="ml-auto flex h-8 w-8 items-center justify-center text-muted-foreground transition hover:bg-secondary hover:text-foreground"
        >
          <PanelRightClose className="h-4 w-4" />
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
        ) : activeTab === "terminal" ? (
          <WorkspaceTerminalPanel slug={slug} />
        ) : (
          <WorkspacePreviewPanel slug={slug} />
        )}
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
  const [rightPanelForceTab, setRightPanelForceTab] = useState<RightTab | null>(null);
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

  // ── Real-time updates ──
  useEventBus((env: SparkEventEnvelope) => {
    if (env.topic !== "workspace.preview.ready") return;
    const data = env.data as { slug?: string; url?: string | null };
    if (data.slug && data.slug === activeWorkspaceSlug && data.url) {
      setRightPanelOpen(true);
      localStorage.setItem("spark-chat-right-panel", "true");
      setRightPanelForceTab("preview");
    }
  });

  const toggleRightPanel = () => {
    setRightPanelOpen((v) => {
      const next = !v;
      localStorage.setItem("spark-chat-right-panel", String(next));
      return next;
    });
  };

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
              forceTab={rightPanelForceTab}
            />
          </div>
        )}
      </div>
    </div>
  );
}
