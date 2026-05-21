import { useCallback, useEffect, useRef, useState } from "react";
import type React from "react";
import { FileRowSkeleton } from "@/components/Skeleton";
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
  SquareTerminal,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import hljs from "highlight.js";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { api, workspaceRawFileUrl } from "@/lib/api";
import type { SessionInfo, WorkspaceFileNode, WorkspaceProject, WorkspaceTerminalEvent } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ChatPanel } from "@/components/ChatPanel";
import { useEventBus } from "@/hooks/useEventBus";
import type { SparkEventEnvelope } from "@/hooks/useEventBus";
import { ThreadRow, threadTitle } from "@/components/chat/ThreadRow";
import { PromptBar } from "@/components/chat/PromptBar";

// ── Types ─────────────────────────────────────────────────────────────────────

type FileView = {
  path: string;
  name: string;
  mime: string;
  content: string | null;
  loading: boolean;
};

type ThreadTab = {
  id: "threads";
  type: "threads";
  name: string;
};

type FileTab = FileView & {
  id: string;
  type: "file";
};

type TerminalTab = {
  id: "terminal";
  type: "terminal";
  name: string;
};

type FilesTab = {
  id: "files";
  type: "files";
  name: string;
};

type WorkspaceTab = ThreadTab | FileTab | TerminalTab | FilesTab;

type PaneNode = {
  type: "pane";
  id: string;
  tabIds: string[];
  activeTabId: string;
};

type SplitNode = {
  type: "split";
  id: string;
  direction: "row" | "column";
  sizes: [number, number];
  children: [WorkspaceLayoutNode, WorkspaceLayoutNode];
};

type WorkspaceLayoutNode = PaneNode | SplitNode;

type DropEdge = "left" | "right" | "top" | "bottom";

const THREAD_TAB_ID = "threads";
const THREAD_TAB: ThreadTab = { id: THREAD_TAB_ID, type: "threads", name: "Threads" };

const TERMINAL_TAB_ID = "terminal";
const TERMINAL_TAB: TerminalTab = { id: TERMINAL_TAB_ID, type: "terminal", name: "Terminal" };

const FILES_TAB_ID = "files";
const FILES_TAB: FilesTab = { id: FILES_TAB_ID, type: "files", name: "Files" };

const makePaneId = () => `pane-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const makeSplitId = () => `split-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
const fileTabId = (path: string) => `file:${path}`;

function createDefaultLayout(): WorkspaceLayoutNode {
  const leftPane: PaneNode = { type: "pane", id: makePaneId(), tabIds: [THREAD_TAB_ID], activeTabId: THREAD_TAB_ID };
  const rightPane: PaneNode = { type: "pane", id: makePaneId(), tabIds: [FILES_TAB_ID, TERMINAL_TAB_ID], activeTabId: FILES_TAB_ID };
  return { type: "split", id: makeSplitId(), direction: "row", sizes: [58, 42], children: [leftPane, rightPane] };
}

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

function languageForFile(filename: string): string | null {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    bash: "bash",
    css: "css",
    env: "ini",
    html: "xml",
    ini: "ini",
    js: "javascript",
    jsx: "javascript",
    json: "json",
    md: "markdown",
    py: "python",
    sh: "bash",
    ts: "typescript",
    tsx: "typescript",
    toml: "ini",
    txt: "plaintext",
    xml: "xml",
    yaml: "yaml",
    yml: "yaml",
  };
  return map[ext] ?? null;
}

function highlightFileContent(content: string, filename: string): { html: string; language: string } {
  const language = languageForFile(filename);
  try {
    if (language && hljs.getLanguage(language)) {
      return {
        html: hljs.highlight(content, { language, ignoreIllegals: true }).value,
        language,
      };
    }
    const result = hljs.highlightAuto(content);
    return { html: result.value, language: result.language ?? "text" };
  } catch {
    return { html: hljs.highlight(content, { language: "plaintext", ignoreIllegals: true }).value, language: "text" };
  }
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
          "spark-list-row group flex items-center gap-1.5 rounded-sm px-1.5 py-0.5 text-[11px] cursor-pointer select-none transition",
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
              className="px-2 py-0.5 text-[11px] italic text-muted-foreground/40"
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

// ── Diff utility ─────────────────────────────────────────────────────────────

type DiffLine = { kind: "context" | "add" | "remove"; text: string };

function computeLineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n");
  const b = after.split("\n");
  // Simple Myers-style diff via LCS DP
  const m = a.length, n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = m - 1; i >= 0; i--)
    for (let j = n - 1; j >= 0; j--)
      dp[i][j] = a[i] === b[j] ? 1 + dp[i + 1][j + 1] : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const result: DiffLine[] = [];
  let i = 0, j = 0;
  while (i < m || j < n) {
    if (i < m && j < n && a[i] === b[j]) {
      result.push({ kind: "context", text: a[i] }); i++; j++;
    } else if (j < n && (i >= m || dp[i + 1][j] <= dp[i][j + 1])) {
      result.push({ kind: "add", text: b[j] }); j++;
    } else {
      result.push({ kind: "remove", text: a[i] }); i++;
    }
  }
  return result;
}

// Per-path baseline content captured the first time a file loads
const _fileBaselines = new Map<string, string>();

// ── File viewer ───────────────────────────────────────────────────────────────

function FileViewer({ file, slug }: { file: FileView; slug: string }) {
  const cat = getFileCategory(file.mime, file.name);
  const [diffMode, setDiffMode] = useState(false);

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
    // Capture baseline on first load
    if (!_fileBaselines.has(file.path)) {
      _fileBaselines.set(file.path, file.content);
    }
    const baseline = _fileBaselines.get(file.path) ?? file.content;
    const hasDiff = file.content !== baseline;
    const highlighted = highlightFileContent(file.content, file.name);
    const diffLines = diffMode ? computeLineDiff(baseline, file.content) : null;
    return (
      <div className="spark-code-pane h-full overflow-auto">
        <div className="sticky top-0 z-10 flex h-7 items-center justify-between border-b border-border bg-background/85 px-3 text-[10px] text-muted-foreground backdrop-blur">
          <span className="truncate font-mono-ui">{file.path}</span>
          <div className="flex items-center gap-2 shrink-0">
            {hasDiff && (
              <button
                type="button"
                onClick={() => setDiffMode((d) => !d)}
                className={`rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wider transition ${
                  diffMode
                    ? "bg-primary/20 text-primary"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                Diff
              </button>
            )}
            <span className="uppercase tracking-[0.12em]">{highlighted.language}</span>
          </div>
        </div>
        {diffMode && diffLines ? (
          <div className="min-h-full font-mono-ui text-[0.72rem] leading-5">
            {diffLines.map((line, i) => (
              <div
                key={i}
                className={
                  line.kind === "add"
                    ? "bg-success/10 text-success px-4"
                    : line.kind === "remove"
                    ? "bg-destructive/10 text-destructive px-4"
                    : "px-4 text-foreground/70"
                }
              >
                <span className="select-none text-muted-foreground/40 mr-2">
                  {line.kind === "add" ? "+" : line.kind === "remove" ? "-" : " "}
                </span>
                {line.text || " "}
              </div>
            ))}
          </div>
        ) : (
          <pre className="hljs min-h-full overflow-visible px-4 py-3 font-mono-ui text-[0.72rem] leading-5">
            <code dangerouslySetInnerHTML={{ __html: highlighted.html }} />
          </pre>
        )}
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
      className="group relative flex w-2 shrink-0 cursor-col-resize items-center justify-center"
    >
      <div className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border transition-colors group-hover:bg-primary/50 group-active:bg-primary/70" />
      <GripVertical className="relative z-10 h-4 w-4 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/50 group-active:text-primary/70" />
    </div>
  );
}

function HorizontalResizeDivider({ onDrag }: { onDrag: (delta: number) => void }) {
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    let lastY = e.clientY;
    const onMove = (mv: MouseEvent) => {
      const delta = mv.clientY - lastY;
      lastY = mv.clientY;
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
      className="group relative flex h-2 shrink-0 cursor-row-resize items-center justify-center"
    >
      <div className="absolute left-0 right-0 top-1/2 h-px -translate-y-1/2 bg-border transition-colors group-hover:bg-primary/50 group-active:bg-primary/70" />
      <GripVertical className="relative z-10 h-4 w-4 rotate-90 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/50 group-active:text-primary/70" />
    </div>
  );
}

function allLayoutTabIds(node: WorkspaceLayoutNode): string[] {
  if (node.type === "pane") return node.tabIds;
  return [...allLayoutTabIds(node.children[0]), ...allLayoutTabIds(node.children[1])];
}

function findActiveFilePath(node: WorkspaceLayoutNode, tabs: WorkspaceTab[]): string | null {
  const activeIds = allLayoutTabIds(node);
  const activeFile = tabs.find((tab) => tab.type === "file" && activeIds.includes(tab.id));
  return activeFile?.type === "file" ? activeFile.path : null;
}

function ensureLayoutTabs(node: WorkspaceLayoutNode, validIds: Set<string>): WorkspaceLayoutNode {
  if (node.type === "pane") {
    const tabIds = node.tabIds.filter((id) => validIds.has(id));
    const safeTabIds = tabIds.length ? tabIds : [THREAD_TAB_ID];
    return {
      ...node,
      tabIds: safeTabIds,
      activeTabId: safeTabIds.includes(node.activeTabId) ? node.activeTabId : safeTabIds[0],
    };
  }
  return {
    ...node,
    children: [
      ensureLayoutTabs(node.children[0], validIds),
      ensureLayoutTabs(node.children[1], validIds),
    ],
  };
}

function removeTabFromLayout(node: WorkspaceLayoutNode, tabId: string): WorkspaceLayoutNode | null {
  if (node.type === "pane") {
    const index = node.tabIds.indexOf(tabId);
    if (index === -1) return node;
    const nextTabIds = node.tabIds.filter((id) => id !== tabId);
    if (!nextTabIds.length) return null;
    const nextActive =
      node.activeTabId === tabId
        ? nextTabIds[Math.min(index, nextTabIds.length - 1)]
        : node.activeTabId;
    return { ...node, tabIds: nextTabIds, activeTabId: nextActive };
  }

  const left = removeTabFromLayout(node.children[0], tabId);
  const right = removeTabFromLayout(node.children[1], tabId);
  if (!left) return right;
  if (!right) return left;
  return { ...node, children: [left, right] };
}

function addTabToFirstPane(node: WorkspaceLayoutNode, tabId: string): WorkspaceLayoutNode {
  if (node.type === "pane") {
    const tabIds = node.tabIds.includes(tabId) ? node.tabIds : [...node.tabIds, tabId];
    return { ...node, tabIds, activeTabId: tabId };
  }
  return { ...node, children: [addTabToFirstPane(node.children[0], tabId), node.children[1]] };
}

function focusTabInLayout(node: WorkspaceLayoutNode, tabId: string): WorkspaceLayoutNode {
  if (node.type === "pane") {
    return node.tabIds.includes(tabId) ? { ...node, activeTabId: tabId } : node;
  }
  return {
    ...node,
    children: [focusTabInLayout(node.children[0], tabId), focusTabInLayout(node.children[1], tabId)],
  };
}

function setPaneActiveTab(node: WorkspaceLayoutNode, paneId: string, tabId: string): WorkspaceLayoutNode {
  if (node.type === "pane") {
    return node.id === paneId ? { ...node, activeTabId: tabId } : node;
  }
  return {
    ...node,
    children: [
      setPaneActiveTab(node.children[0], paneId, tabId),
      setPaneActiveTab(node.children[1], paneId, tabId),
    ],
  };
}

function reorderTabInPane(
  node: WorkspaceLayoutNode,
  paneId: string,
  draggedId: string,
  targetId: string,
): WorkspaceLayoutNode {
  if (node.type === "pane") {
    if (node.id !== paneId || draggedId === targetId) return node;
    const without = node.tabIds.filter((id) => id !== draggedId);
    const targetIndex = without.indexOf(targetId);
    if (targetIndex === -1) return node;
    const tabIds = [...without.slice(0, targetIndex), draggedId, ...without.slice(targetIndex)];
    return { ...node, tabIds, activeTabId: draggedId };
  }
  return {
    ...node,
    children: [
      reorderTabInPane(node.children[0], paneId, draggedId, targetId),
      reorderTabInPane(node.children[1], paneId, draggedId, targetId),
    ],
  };
}

function splitPaneWithTab(
  node: WorkspaceLayoutNode,
  paneId: string,
  tabId: string,
  edge: DropEdge,
): WorkspaceLayoutNode {
  if (node.type === "pane") {
    if (node.id !== paneId) return node;
    const cleanNode = removeTabFromLayout(node, tabId);
    if (!cleanNode || cleanNode.type !== "pane") return node;
    const newPane: PaneNode = { type: "pane", id: makePaneId(), tabIds: [tabId], activeTabId: tabId };
    const direction = edge === "left" || edge === "right" ? "row" : "column";
    const children: [WorkspaceLayoutNode, WorkspaceLayoutNode] =
      edge === "left" || edge === "top" ? [newPane, cleanNode] : [cleanNode, newPane];
    return { type: "split", id: makeSplitId(), direction, sizes: [50, 50], children };
  }
  return {
    ...node,
    children: [
      splitPaneWithTab(node.children[0], paneId, tabId, edge),
      splitPaneWithTab(node.children[1], paneId, tabId, edge),
    ],
  };
}

function moveTabToPane(node: WorkspaceLayoutNode, paneId: string, tabId: string): WorkspaceLayoutNode {
  const targetAlreadyHasTab = (layout: WorkspaceLayoutNode): boolean => {
    if (layout.type === "pane") return layout.id === paneId && layout.tabIds.includes(tabId);
    return targetAlreadyHasTab(layout.children[0]) || targetAlreadyHasTab(layout.children[1]);
  };
  if (targetAlreadyHasTab(node)) return setPaneActiveTab(node, paneId, tabId);

  const without = removeTabFromLayout(node, tabId) ?? createDefaultLayout();
  const addToPane = (layout: WorkspaceLayoutNode): WorkspaceLayoutNode => {
    if (layout.type === "pane") {
      if (layout.id !== paneId) return layout;
      const tabIds = layout.tabIds.includes(tabId) ? layout.tabIds : [...layout.tabIds, tabId];
      return { ...layout, tabIds, activeTabId: tabId };
    }
    return { ...layout, children: [addToPane(layout.children[0]), addToPane(layout.children[1])] };
  };
  return addToPane(without);
}

function resizeSplit(node: WorkspaceLayoutNode, splitId: string, delta: number): WorkspaceLayoutNode {
  if (node.type === "pane") return node;
  if (node.id === splitId) {
    const next = Math.min(80, Math.max(20, node.sizes[0] + delta));
    return { ...node, sizes: [next, 100 - next] };
  }
  return {
    ...node,
    children: [resizeSplit(node.children[0], splitId, delta), resizeSplit(node.children[1], splitId, delta)],
  };
}

function paneContainsTab(node: WorkspaceLayoutNode, paneId: string, tabId: string): boolean {
  if (node.type === "pane") return node.id === paneId && node.tabIds.includes(tabId);
  return paneContainsTab(node.children[0], paneId, tabId) || paneContainsTab(node.children[1], paneId, tabId);
}


// ── Projects sidebar ──────────────────────────────────────────────────────────

function ProjectsSidebar({
  projects,
  activeSlug,
  onSelect,
  onCreate,
  onDelete,
  loading,
  collapsed,
  onToggleCollapse,
  panelWidth,
}: {
  projects: WorkspaceProject[];
  activeSlug: string | null;
  onSelect: (slug: string) => void;
  onCreate: (name: string) => Promise<void>;
  onDelete: (slug: string) => Promise<void>;
  loading: boolean;
  collapsed: boolean;
  onToggleCollapse: () => void;
  panelWidth: number;
}) {
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDeleteSlug, setConfirmDeleteSlug] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!confirmDeleteSlug) return;
    setDeleting(true);
    try {
      await onDelete(confirmDeleteSlug);
      setConfirmDeleteSlug(null);
    } finally {
      setDeleting(false);
    }
  };

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
      <div className="spark-glass-panel flex w-9 shrink-0 flex-col items-center gap-1 border-r border-border py-2">
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
    <div style={{ width: panelWidth }} className="spark-glass-panel flex shrink-0 flex-col overflow-hidden border-r border-border">
      <div className="spark-panel-header shrink-0 border-b border-border p-2">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <FolderOpen className="h-4 w-4 text-muted-foreground" />
              <h2 className="truncate text-sm font-semibold">Projects</h2>
            </div>
            <p className="mt-0.5 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
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
          <div className="flex flex-col py-1">
            {Array.from({ length: 5 }).map((_, i) => <FileRowSkeleton key={i} />)}
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
          <div
            key={p.slug}
            className={cn(
              "spark-list-row group relative w-full px-2 py-1.5 text-xs transition cursor-pointer",
              activeSlug === p.slug
                ? "border-r-2 border-primary bg-primary/15 text-foreground"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
            onClick={() => onSelect(p.slug)}
          >
            <div className="flex items-center gap-2 pr-5">
              <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-300/70" />
              <span className="truncate font-medium">{p.name}</span>
            </div>
            <div className="mt-0.5 pl-5 text-[11px] text-muted-foreground/50">
              {p.file_count} {p.file_count === 1 ? "file" : "files"}
            </div>
            <button
              type="button"
              title="Delete project"
              className="absolute right-2 top-1/2 -translate-y-1/2 hidden text-muted-foreground/50 hover:text-destructive group-hover:block"
              onClick={(e) => {
                e.stopPropagation();
                setConfirmDeleteSlug(p.slug);
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}

        {confirmDeleteSlug && (
          <div className="mx-2 mt-2 flex flex-col gap-1.5 rounded-sm border border-destructive/40 bg-background p-2">
            <p className="text-xs text-foreground">
              Delete <span className="font-semibold">{confirmDeleteSlug}</span>?
            </p>
            <p className="text-[11px] text-muted-foreground">
              This will permanently remove the project and all its files.
            </p>
            <div className="flex gap-1">
              <Button
                size="sm"
                variant="destructive"
                className="h-6 flex-1 text-xs"
                onClick={() => void handleDelete()}
                disabled={deleting}
              >
                {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : "Delete"}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 w-6 p-0"
                onClick={() => setConfirmDeleteSlug(null)}
                disabled={deleting}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          </div>
        )}

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
  reloadTrigger,
}: {
  slug: string;
  activeId: string | null;
  onOpen: (id: string, session: SessionInfo) => void;
  onNewThread: () => void;
  onSessionsChange: (sessions: SessionInfo[]) => void;
  panelWidth: number;
  reloadTrigger: number;
}) {
  const [threads, setThreads] = useState<SessionInfo[]>([]);
  const [loadingThreads, setLoadingThreads] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target instanceof Element ? e.target : null;
      if (target?.closest(".spark-terminal-pane")) return;
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

  useEffect(() => {
    if (reloadTrigger > 0) void loadThreads();
  }, [reloadTrigger, loadThreads]);

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
    <div style={{ width: panelWidth }} className="spark-glass-panel flex shrink-0 flex-col overflow-hidden border-r border-border">
      {/* Header */}
      <div className="spark-panel-header shrink-0 border-b border-border p-2">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 text-muted-foreground" />
              <h2 className="truncate text-sm font-semibold">Threads</h2>
              <Badge variant="secondary" className="h-5 text-[10px]">
                {threads.length}
              </Badge>
            </div>
            <p className="mt-0.5 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
              Project chats
            </p>
          </div>
          <Button
            size="sm"
            className="h-7 shrink-0 gap-1.5 px-2 text-xs"
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
            className="h-8 pl-8 pr-16 text-xs"
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
          <div className="flex flex-col py-1">
            {Array.from({ length: 4 }).map((_, i) => <FileRowSkeleton key={i} />)}
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

  const handleUpload = async (files: File[]) => {
    const res = await api.uploadWorkspaceFiles(slug, files, "files");
    const refs = res.saved.map((f) => `@files/${f.filename}`).join(" ");
    setMsg((prev) => {
      const prefix = prev.trimEnd();
      return prefix ? `${prefix}\n${refs} ` : `${refs} `;
    });
  };

  return (
    <div className="flex flex-1 flex-col">
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

      <PromptBar
        input={msg}
        setInput={setMsg}
        streaming={false}
        onSend={() => void handleSend()}
        onStop={() => {}}
        onUploadFiles={handleUpload}
        disabled={starting}
        workspaceSlug={slug}
      />
    </div>
  );
}

// ── Workspace editor tabs ─────────────────────────────────────────────────────

function WorkspaceTabButton({
  tab,
  active,
  paneId,
  onActivate,
  onClose,
  onReorder,
}: {
  tab: WorkspaceTab;
  active: boolean;
  paneId: string;
  onActivate: () => void;
  onClose: () => void;
  onReorder: (paneId: string, draggedId: string, targetId: string) => void;
}) {
  return (
    <button
      type="button"
      draggable
      title={tab.type === "file" ? tab.path : tab.type === "terminal" ? "Terminal" : tab.type === "files" ? "Files" : "Workspace threads"}
      onClick={onActivate}
      onDragStart={(e) => {
        e.dataTransfer.setData("application/x-spark-tab", tab.id);
        e.dataTransfer.effectAllowed = "move";
      }}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("application/x-spark-tab")) e.preventDefault();
      }}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        const draggedId = e.dataTransfer.getData("application/x-spark-tab");
        if (draggedId) onReorder(paneId, draggedId, tab.id);
      }}
      className={cn(
        "group flex h-8 max-w-52 shrink-0 items-center gap-1.5 border-r border-border px-2.5 text-[11px] transition",
        active
          ? "bg-background text-foreground"
          : "bg-card/50 text-muted-foreground hover:bg-secondary hover:text-foreground",
      )}
    >
      {tab.type === "threads" ? (
        <MessageSquare className="h-3.5 w-3.5 shrink-0" />
      ) : tab.type === "terminal" ? (
        <SquareTerminal className="h-3.5 w-3.5 shrink-0" />
      ) : tab.type === "files" ? (
        <FileText className="h-3.5 w-3.5 shrink-0" />
      ) : (
        <FileIcon name={tab.name} />
      )}
      <span className="truncate">{tab.name}</span>
      {tab.type === "file" && (
        <span
          role="button"
          tabIndex={0}
          className="ml-1 grid h-4 w-4 shrink-0 place-items-center rounded-sm text-muted-foreground/50 opacity-0 transition hover:bg-secondary hover:text-foreground group-hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              e.stopPropagation();
              onClose();
            }
          }}
          aria-label={`Close ${tab.name}`}
        >
          <X className="h-3 w-3" />
        </span>
      )}
    </button>
  );
}

function PaneDropZone({
  edge,
  topOffset,
  onDropTab,
}: {
  edge: DropEdge;
  topOffset: "top-0" | "top-8";
  onDropTab: (tabId: string, edge: DropEdge) => void;
}) {
  const edgeClasses: Record<DropEdge, string> = {
    left: `left-0 ${topOffset} bottom-0 w-1/4 border-r`,
    right: `right-0 ${topOffset} bottom-0 w-1/4 border-l`,
    top: `left-0 right-0 ${topOffset} h-1/4 border-b`,
    bottom: "left-0 right-0 bottom-0 h-1/4 border-t",
  };

  return (
    <div
      className={cn(
        "absolute z-20 border-primary/0 bg-primary/0 transition-colors hover:border-primary/40 hover:bg-primary/10",
        edgeClasses[edge],
      )}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("application/x-spark-tab")) e.preventDefault();
      }}
      onDrop={(e) => {
        e.preventDefault();
        e.stopPropagation();
        const tabId = e.dataTransfer.getData("application/x-spark-tab");
        if (tabId) onDropTab(tabId, edge);
      }}
    />
  );
}

function WorkspacePane({
  pane,
  tabs,
  slug,
  threadContent,
  activePath,
  onActivate,
  onClose,
  onMoveToPane,
  onReorder,
  onSplit,
  onOpenFile,
  hideTabStrip,
  isRightPanel,
  onToggleRightPanel,
}: {
  pane: PaneNode;
  tabs: WorkspaceTab[];
  slug: string;
  threadContent: React.ReactNode;
  activePath: string | null;
  onActivate: (paneId: string, tabId: string) => void;
  onClose: (tabId: string) => void;
  onMoveToPane: (paneId: string, tabId: string) => void;
  onReorder: (paneId: string, draggedId: string, targetId: string) => void;
  onSplit: (paneId: string, tabId: string, edge: DropEdge) => void;
  onOpenFile: (node: WorkspaceFileNode) => void;
  hideTabStrip?: boolean;
  isRightPanel?: boolean;
  onToggleRightPanel?: () => void;
}) {
  const [draggingOver, setDraggingOver] = useState(false);
  const paneTabs = pane.tabIds
    .map((id) => tabs.find((tab) => tab.id === id))
    .filter((tab): tab is WorkspaceTab => Boolean(tab));
  const activeTab = paneTabs.find((tab) => tab.id === pane.activeTabId) ?? paneTabs[0] ?? THREAD_TAB;

  return (
    <div
      className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-border bg-card/30"
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("application/x-spark-tab")) {
          e.preventDefault();
          setDraggingOver(true);
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDraggingOver(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDraggingOver(false);
        const tabId = e.dataTransfer.getData("application/x-spark-tab");
        if (tabId) onMoveToPane(pane.id, tabId);
      }}
    >
      {!hideTabStrip && (
        <div className="spark-tabbar flex h-8 shrink-0 overflow-x-auto border-b border-border scrollbar-none">
          {paneTabs.map((tab) => (
            <WorkspaceTabButton
              key={tab.id}
              tab={tab}
              paneId={pane.id}
              active={activeTab.id === tab.id}
              onActivate={() => onActivate(pane.id, tab.id)}
              onClose={() => onClose(tab.id)}
              onReorder={onReorder}
            />
          ))}
          {isRightPanel && onToggleRightPanel && (
            <div className="ml-auto flex shrink-0 items-center border-l border-border">
              <button
                type="button"
                title="Collapse right panel"
                onClick={onToggleRightPanel}
                className="flex h-8 w-8 items-center justify-center text-muted-foreground transition hover:bg-secondary hover:text-foreground"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      )}

      {draggingOver && (
        <>
          <PaneDropZone edge="left" topOffset={hideTabStrip ? "top-0" : "top-8"} onDropTab={(tabId, edge) => onSplit(pane.id, tabId, edge)} />
          <PaneDropZone edge="right" topOffset={hideTabStrip ? "top-0" : "top-8"} onDropTab={(tabId, edge) => onSplit(pane.id, tabId, edge)} />
          <PaneDropZone edge="top" topOffset={hideTabStrip ? "top-0" : "top-8"} onDropTab={(tabId, edge) => onSplit(pane.id, tabId, edge)} />
          <PaneDropZone edge="bottom" topOffset={hideTabStrip ? "top-0" : "top-8"} onDropTab={(tabId, edge) => onSplit(pane.id, tabId, edge)} />
        </>
      )}

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {activeTab.type === "threads" ? threadContent
          : activeTab.type === "terminal" ? <WorkspaceTerminalPanel slug={slug} />
          : activeTab.type === "files" ? <FileTreePane slug={slug} activePath={activePath} onOpenFile={onOpenFile} />
          : <FileViewer file={activeTab} slug={slug} />}
      </div>
    </div>
  );
}

function WorkspaceLayoutView({
  node,
  tabs,
  slug,
  threadContent,
  activePath,
  primaryHeaderPaneId,
  rightPanelCollapsed,
  onActivate,
  onClose,
  onMoveToPane,
  onReorder,
  onSplit,
  onResizeSplit,
  onOpenFile,
  onToggleRightPanel,
}: {
  node: WorkspaceLayoutNode;
  tabs: WorkspaceTab[];
  slug: string;
  threadContent: React.ReactNode;
  activePath: string | null;
  primaryHeaderPaneId: string;
  rightPanelCollapsed: boolean;
  onActivate: (paneId: string, tabId: string) => void;
  onClose: (tabId: string) => void;
  onMoveToPane: (paneId: string, tabId: string) => void;
  onReorder: (paneId: string, draggedId: string, targetId: string) => void;
  onSplit: (paneId: string, tabId: string, edge: DropEdge) => void;
  onResizeSplit: (splitId: string, delta: number) => void;
  onOpenFile: (node: WorkspaceFileNode) => void;
  onToggleRightPanel: () => void;
}) {
  if (node.type === "pane") {
    const isRightPanel = node.tabIds.includes(FILES_TAB_ID);
    return (
      <WorkspacePane
        pane={node}
        tabs={tabs}
        slug={slug}
        threadContent={threadContent}
        activePath={activePath}
        hideTabStrip={node.id === primaryHeaderPaneId}
        isRightPanel={isRightPanel}
        onToggleRightPanel={isRightPanel ? onToggleRightPanel : undefined}
        onActivate={onActivate}
        onClose={onClose}
        onMoveToPane={onMoveToPane}
        onReorder={onReorder}
        onSplit={onSplit}
        onOpenFile={onOpenFile}
      />
    );
  }

  const sharedProps = {
    tabs, slug, threadContent, activePath, primaryHeaderPaneId,
    rightPanelCollapsed, onActivate, onClose, onMoveToPane,
    onReorder, onSplit, onResizeSplit, onOpenFile, onToggleRightPanel,
  };

  // For row splits, collapse the right child when it contains the Files tab
  if (node.direction === "row") {
    const rightHasFilesTab = allLayoutTabIds(node.children[1]).includes(FILES_TAB_ID);
    if (rightPanelCollapsed && rightHasFilesTab) {
      return (
        <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
          <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
            <WorkspaceLayoutView node={node.children[0]} {...sharedProps} />
          </div>
          <div className="spark-glass-panel flex w-9 shrink-0 flex-col items-center gap-1 border-l border-border py-2">
            <button
              type="button"
              title="Expand right panel"
              onClick={onToggleRightPanel}
              className="rounded p-1.5 text-muted-foreground transition hover:bg-secondary hover:text-foreground"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <div className="my-1 h-px w-6 bg-border" />
            <FileText className="h-3.5 w-3.5 text-muted-foreground/30" />
            <SquareTerminal className="h-3.5 w-3.5 text-muted-foreground/30" />
          </div>
        </div>
      );
    }
  }

  const firstStyle = { flexBasis: `${node.sizes[0]}%` };
  const secondStyle = { flexBasis: `${node.sizes[1]}%` };

  return (
    <div className={cn("flex min-h-0 min-w-0 flex-1 overflow-hidden", node.direction === "column" && "flex-col")}>
      <div className="flex min-h-0 min-w-0 overflow-hidden" style={firstStyle}>
        <WorkspaceLayoutView node={node.children[0]} {...sharedProps} />
      </div>
      {node.direction === "row" ? (
        <ResizeDivider onDrag={(delta) => onResizeSplit(node.id, delta * 0.15)} />
      ) : (
        <HorizontalResizeDivider onDrag={(delta) => onResizeSplit(node.id, delta * 0.15)} />
      )}
      <div className="flex min-h-0 min-w-0 overflow-hidden" style={secondStyle}>
        <WorkspaceLayoutView node={node.children[1]} {...sharedProps} />
      </div>
    </div>
  );
}

// ── Workspace terminal ────────────────────────────────────────────────────────

function WorkspaceTerminalPanel({ slug }: { slug: string }) {
  const terminalHostRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const shellRunIdRef = useRef<string | null>(null);
  const resizeTimerRef = useRef<number | null>(null);
  const [shellRunId, setShellRunId] = useState<string | null>(null);
  const [shellStatus, setShellStatus] = useState<"connecting" | "running" | "stopped" | "failed">("connecting");

  const sendResize = useCallback(() => {
    const term = terminalRef.current;
    const fit = fitAddonRef.current;
    const runId = shellRunIdRef.current;
    if (!term || !fit || !runId) return;
    try {
      fit.fit();
      void api.resizeWorkspaceTerminal(slug, runId, term.rows, term.cols).catch(() => {});
    } catch {
      // The terminal may be hidden during pane changes; fit again on the next resize/focus.
    }
  }, [slug]);

  useEffect(() => {
    const host = terminalHostRef.current;
    if (!host) return;

    const term = new Terminal({
      allowProposedApi: false,
      convertEol: false,
      cursorBlink: true,
      cursorStyle: "block",
      fontFamily: '"Courier Prime", "SF Mono", Menlo, monospace',
      fontSize: 12,
      lineHeight: 1.25,
      scrollback: 4000,
      theme: {
        background: "#0d0d0d",
        foreground: "#d8d0c0",
        cursor: "#FDA632",
        selectionBackground: "#FDA63244",
        black: "#151515",
        red: "#f97316",
        green: "#8fd694",
        yellow: "#FDA632",
        blue: "#8fb4ff",
        magenta: "#cb9cf2",
        cyan: "#8bd7d2",
        white: "#f0ece4",
        brightBlack: "#6b6b60",
        brightRed: "#ff9a5f",
        brightGreen: "#b7e4b7",
        brightYellow: "#ffc875",
        brightBlue: "#b3c8ff",
        brightMagenta: "#dfb5ff",
        brightCyan: "#aee8e4",
        brightWhite: "#ffffff",
      },
    });
    const fit = new FitAddon();
    terminalRef.current = term;
    fitAddonRef.current = fit;
    term.loadAddon(fit);
    term.open(host);
    term.attachCustomKeyEventHandler((event) => {
      event.stopPropagation();
      return true;
    });
    term.writeln("\x1b[2mStarting workspace shell...\x1b[0m");
    setShellStatus("connecting");

    const dataDisposable = term.onData((data) => {
      const runId = shellRunIdRef.current;
      if (!runId) return;
      void api.sendWorkspaceTerminalInput(slug, runId, data).catch((e) => {
        term.writeln(`\r\n\x1b[31mFailed to send input: ${String(e)}\x1b[0m`);
      });
    });

    let cancelled = false;
    void api.runWorkspaceTerminalCommand(slug).then((run) => {
      if (cancelled) return;
      setShellRunId(run.run_id);
      shellRunIdRef.current = run.run_id;
      const source = api.streamWorkspaceTerminalRun(slug, run.run_id);
      eventSourceRef.current = source;
      source.onmessage = (ev) => {
        const data = JSON.parse(ev.data) as WorkspaceTerminalEvent;
        if (data.type === "output") {
          term.write(data.text);
          return;
        }
        if (data.type === "state") {
          setShellStatus(data.status === "running" ? "running" : "connecting");
          if (data.status === "running") {
            window.setTimeout(sendResize, 30);
            term.focus();
          }
          return;
        }
        if (data.type === "done") {
          setShellStatus(data.status === "stopped" ? "stopped" : "failed");
          term.writeln(`\r\n\x1b[2m[terminal ${data.status}${data.exit_code !== null ? `:${data.exit_code}` : ""}]\x1b[0m`);
          source.close();
          if (eventSourceRef.current === source) eventSourceRef.current = null;
        }
      };
      source.onerror = () => {
        setShellStatus("failed");
        term.writeln("\r\n\x1b[31m[terminal stream disconnected]\x1b[0m");
        source.close();
        if (eventSourceRef.current === source) eventSourceRef.current = null;
      };
    }).catch((e) => {
      if (cancelled) return;
      setShellStatus("failed");
      term.writeln(`\r\n\x1b[31mFailed to start shell: ${String(e)}\x1b[0m`);
    });

    const observer = new ResizeObserver(() => {
      if (resizeTimerRef.current !== null) window.clearTimeout(resizeTimerRef.current);
      resizeTimerRef.current = window.setTimeout(sendResize, 80);
    });
    observer.observe(host);
    window.setTimeout(sendResize, 30);

    return () => {
      cancelled = true;
      observer.disconnect();
      dataDisposable.dispose();
      eventSourceRef.current?.close();
      eventSourceRef.current = null;
      if (resizeTimerRef.current !== null) window.clearTimeout(resizeTimerRef.current);
      if (shellRunIdRef.current) void api.stopWorkspaceTerminalRun(slug, shellRunIdRef.current).catch(() => {});
      shellRunIdRef.current = null;
      terminalRef.current = null;
      fitAddonRef.current = null;
      term.dispose();
    };
  }, [sendResize, slug]);

  return (
    <div
      className="spark-terminal-pane relative min-h-0 flex-1 overflow-hidden"
      onMouseDown={() => terminalRef.current?.focus()}
      onClick={() => terminalRef.current?.focus()}
    >
      <div ref={terminalHostRef} className="h-full w-full px-2 py-2" />
      <div className="pointer-events-none absolute right-2 top-2 rounded-sm border border-border bg-background/75 px-2 py-1 text-[10px] uppercase tracking-[0.12em] text-muted-foreground backdrop-blur">
        {shellStatus}
        {shellRunId ? ` · ${shellRunId.slice(-4)}` : ""}
      </div>
    </div>
  );
}

// ── File tree pane (renders inside workspace layout) ──────────────────────────

function FileTreePane({
  slug,
  activePath,
  onOpenFile,
}: {
  slug: string;
  activePath: string | null;
  onOpenFile: (node: WorkspaceFileNode) => void;
}) {
  const [tree, setTree] = useState<WorkspaceFileNode[]>([]);
  const [loadingTree, setLoadingTree] = useState(false);
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

  useEffect(() => { void loadTree(); }, [loadTree]);

  const handleDelete = async (node: WorkspaceFileNode) => {
    if (!confirm(`Delete ${node.path}?`)) return;
    try {
      await api.deleteWorkspaceFile(slug, node.path);
      void loadTree();
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
      void loadTree();
    } catch (e) {
      console.error("Upload failed", e);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between border-b border-border px-2 py-1">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60">Explorer</span>
        <div className="flex items-center gap-1">
          {uploading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
          <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="Upload files" onClick={() => fileInputRef.current?.click()}>
            <Upload className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="Refresh" onClick={() => void loadTree()}>
            <Loader2 className={cn("h-3.5 w-3.5", loadingTree ? "animate-spin" : "opacity-40")} />
          </Button>
        </div>
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={(e) => e.target.files && void handleUpload(e.target.files)} />
      </div>
      <div
        className={cn("min-h-0 flex-1 overflow-y-auto py-1 transition-all", dragOver && "bg-primary/5 ring-2 ring-inset ring-primary/20")}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files.length) void handleUpload(e.dataTransfer.files); }}
      >
        {loadingTree && !tree.length && (
          <div className="flex items-center justify-center py-8 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        )}
        {!loadingTree && tree.length === 0 && (
          <div className="flex flex-col items-center gap-2 py-8 text-center text-xs text-muted-foreground/60">
            <Upload className="h-6 w-6 opacity-30" />
            <p>No files yet.<br />Drop files here or click upload.</p>
          </div>
        )}
        {tree.map((node) => (
          <FileNodeRow
            key={node.path}
            node={node}
            depth={0}
            onSelect={onOpenFile}
            selectedPath={activePath}
            onDelete={(n) => void handleDelete(n)}
          />
        ))}
      </div>
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
  const [threadsReloadTrigger, setThreadsReloadTrigger] = useState(0);

  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const STATIC_TABS: WorkspaceTab[] = [THREAD_TAB, FILES_TAB, TERMINAL_TAB];
  const [workspaceTabs, setWorkspaceTabs] = useState<WorkspaceTab[]>(STATIC_TABS);
  const [workspaceLayout, setWorkspaceLayout] = useState<WorkspaceLayoutNode>(() => createDefaultLayout());

  const [projectsCollapsed, setProjectsCollapsed] = useState<boolean>(() => {
    return localStorage.getItem("spark-workspace-projects-collapsed") === "true";
  });

  const [rightPanelCollapsed, setRightPanelCollapsed] = useState<boolean>(() => {
    return localStorage.getItem("spark-workspace-right-collapsed") === "true";
  });

  const toggleRightPanel = () => {
    setRightPanelCollapsed((v) => {
      const next = !v;
      localStorage.setItem("spark-workspace-right-collapsed", String(next));
      return next;
    });
  };

  const [[projectsWidth, threadsWidth], setPanelWidths] = useState<[number, number]>(() => {
    try {
      const raw = localStorage.getItem("spark-workspace-widths");
      if (raw) {
        const p = JSON.parse(raw) as unknown;
        if (Array.isArray(p) && p.length >= 2 && p.every((x) => typeof x === "number"))
          return [Math.max(160, p[0] as number), Math.max(200, p[1] as number)];
      }
    } catch { /* ignore */ }
    return [220, 280];
  });

  const handleProjectsDrag = useCallback((delta: number) => {
    setPanelWidths(([p, t]) => {
      const next: [number, number] = [Math.max(160, p + delta), t];
      localStorage.setItem("spark-workspace-widths", JSON.stringify(next));
      return next;
    });
  }, []);

  const handleThreadsDrag = useCallback((delta: number) => {
    setPanelWidths(([p, t]) => {
      const next: [number, number] = [p, Math.max(200, t + delta)];
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

  useEffect(() => {
    if (!activeSlug) {
      setWorkspaceTabs(STATIC_TABS);
      setWorkspaceLayout(createDefaultLayout());
      return;
    }

    try {
      const raw = localStorage.getItem(`spark-workspace-editor:${activeSlug}`);
      if (!raw) {
        setWorkspaceTabs(STATIC_TABS);
        setWorkspaceLayout(createDefaultLayout());
        return;
      }

      const parsed = JSON.parse(raw) as { tabs?: WorkspaceTab[]; layout?: WorkspaceLayoutNode };
      const fileTabs = Array.isArray(parsed.tabs)
        ? parsed.tabs.filter((tab): tab is FileTab => tab?.type === "file" && typeof tab.path === "string")
        : [];
      const tabs = [...STATIC_TABS, ...fileTabs];
      const uniqueTabs = tabs.filter((tab, index, arr) => arr.findIndex((item) => item.id === tab.id) === index);
      const validIds = new Set(uniqueTabs.map((tab) => tab.id));
      setWorkspaceTabs(uniqueTabs);

      let finalLayout = parsed.layout ? ensureLayoutTabs(parsed.layout, validIds) : createDefaultLayout();
      // If permanent tabs are missing (e.g. from a layout saved before they were added), reset to default
      const presentIds = new Set(allLayoutTabIds(finalLayout));
      if (!presentIds.has(FILES_TAB_ID) || !presentIds.has(TERMINAL_TAB_ID)) {
        finalLayout = createDefaultLayout();
        for (const ft of fileTabs) finalLayout = addTabToFirstPane(finalLayout, ft.id);
      }
      setWorkspaceLayout(finalLayout);
    } catch {
      setWorkspaceTabs(STATIC_TABS);
      setWorkspaceLayout(createDefaultLayout());
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSlug]);

  useEffect(() => {
    if (!activeSlug) return;
    localStorage.setItem(
      `spark-workspace-editor:${activeSlug}`,
      JSON.stringify({ tabs: workspaceTabs.filter((tab) => tab.type === "file"), layout: workspaceLayout }),
    );
  }, [activeSlug, workspaceLayout, workspaceTabs]);

  const handleCreate = async (name: string) => {
    const res = await api.createWorkspaceProject(name);
    await loadProjects();
    setActiveSlug(res.slug);
    setActiveThreadId(null);
    setActiveSession(null);
  };

  const handleDeleteProject = async (slug: string) => {
    await api.deleteWorkspaceProject(slug);
    await loadProjects();
    if (activeSlug === slug) {
      setActiveSlug(null);
      setActiveThreadId(null);
      setActiveSession(null);
    }
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
    setThreadsReloadTrigger((n) => n + 1);
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

  const handleOpenFile = (node: WorkspaceFileNode) => {
    if (!activeSlug) return;
    const mime = node.mime ?? "application/octet-stream";
    const cat = getFileCategory(mime, node.name);
    const tabId = fileTabId(node.path);

    setWorkspaceTabs((prev) => {
      if (prev.some((tab) => tab.id === tabId)) return prev;
      return [
        ...prev,
        {
          id: tabId,
          type: "file",
          path: node.path,
          name: node.name,
          mime,
          content: null,
          loading: cat === "text",
        },
      ];
    });
    setWorkspaceLayout((prev) =>
      allLayoutTabIds(prev).includes(tabId) ? focusTabInLayout(prev, tabId) : addTabToFirstPane(prev, tabId),
    );

    if (cat === "text") {
      void api
        .getWorkspaceFile(activeSlug, node.path)
        .then((res) => {
          setWorkspaceTabs((prev) =>
            prev.map((tab) =>
              tab.id === tabId && tab.type === "file"
                ? { ...tab, content: res.content, loading: false }
                : tab,
            ),
          );
        })
        .catch((e) => {
          setWorkspaceTabs((prev) =>
            prev.map((tab) =>
              tab.id === tabId && tab.type === "file"
                ? { ...tab, content: `Error loading file: ${e}`, loading: false }
                : tab,
            ),
          );
        });
    }
  };

  const PERMANENT_TAB_IDS = new Set([THREAD_TAB_ID, FILES_TAB_ID, TERMINAL_TAB_ID]);

  const handleCloseTab = (tabId: string) => {
    if (PERMANENT_TAB_IDS.has(tabId)) return;
    setWorkspaceTabs((prev) => prev.filter((tab) => tab.id !== tabId));
    setWorkspaceLayout((prev) => removeTabFromLayout(prev, tabId) ?? createDefaultLayout());
  };

  const handleMoveTabToPane = (paneId: string, tabId: string) => {
    setWorkspaceLayout((prev) => moveTabToPane(prev, paneId, tabId));
  };

  const handleSplitTab = (paneId: string, tabId: string, edge: DropEdge) => {
    if (tabId === THREAD_TAB_ID) return;
    setWorkspaceLayout((prev) => {
      const layout = paneContainsTab(prev, paneId, tabId)
        ? prev
        : removeTabFromLayout(prev, tabId) ?? createDefaultLayout();
      return splitPaneWithTab(layout, paneId, tabId, edge);
    });
  };

  const handleReorderTab = (paneId: string, draggedId: string, targetId: string) => {
    setWorkspaceLayout((prev) => reorderTabInPane(prev, paneId, draggedId, targetId));
  };

  const activeFilePath = activeSlug ? findActiveFilePath(workspaceLayout, workspaceTabs) : null;

  const threadContent = activeSlug ? (
    newThread ? (
      <WorkspaceNewThread
        key={`new-${activeSlug}`}
        slug={activeSlug}
        onCreated={handleThreadCreated}
        onCancel={() => setNewThread(false)}
      />
    ) : activeThreadId ? (
      <>
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
        </div>

        <ChatPanel
          sessionId={activeThreadId}
          sessionTitle={activeSession ? threadTitle(activeSession) : null}
          initialMessage={pendingInitialMsg ?? undefined}
          workspaceSlug={activeSlug}
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
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center text-muted-foreground">
        <MessageSquare className="mb-4 h-12 w-12 opacity-30" />
        <p className="text-sm font-medium text-foreground">Select a thread</p>
        <p className="mt-1 max-w-sm text-xs opacity-75">
          Pick a thread from the list or click New to start one.
        </p>
      </div>
    )
  ) : null;

  return (
    <div className="flex h-full max-h-screen min-h-0 overflow-hidden border-t border-border bg-card/70 backdrop-blur-xl">
      {/* Projects panel */}
      <ProjectsSidebar
        projects={projects}
        activeSlug={activeSlug}
        onSelect={handleSelectProject}
        onCreate={handleCreate}
        onDelete={handleDeleteProject}
        loading={loadingProjects}
        collapsed={projectsCollapsed}
        onToggleCollapse={toggleProjectsCollapse}
        panelWidth={projectsWidth}
      />

      {/* Divider: projects ↔ threads/chat */}
      {!projectsCollapsed && <ResizeDivider onDrag={handleProjectsDrag} />}

      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
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
              reloadTrigger={threadsReloadTrigger}
            />
            <ResizeDivider onDrag={handleThreadsDrag} />
          </>
        )}

        {/* Workspace tile area */}
        {activeSlug ? (
          <WorkspaceLayoutView
            node={workspaceLayout}
            tabs={workspaceTabs}
            slug={activeSlug}
            threadContent={threadContent}
            activePath={activeFilePath}
            primaryHeaderPaneId=""
            rightPanelCollapsed={rightPanelCollapsed}
            onActivate={(paneId, tabId) => setWorkspaceLayout((prev) => setPaneActiveTab(prev, paneId, tabId))}
            onClose={handleCloseTab}
            onMoveToPane={handleMoveTabToPane}
            onReorder={handleReorderTab}
            onSplit={handleSplitTab}
            onResizeSplit={(splitId, delta) => setWorkspaceLayout((prev) => resizeSplit(prev, splitId, delta))}
            onOpenFile={handleOpenFile}
            onToggleRightPanel={toggleRightPanel}
          />
        ) : (
          <div className="flex h-full flex-1 flex-col items-center justify-center px-6 text-center text-muted-foreground">
            <FolderOpen className="mb-4 h-12 w-12 opacity-30" />
            <p className="text-sm font-medium text-foreground">Select a project</p>
            <p className="mt-1 max-w-sm text-xs opacity-75">
              Choose a project from the left panel to get started.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
