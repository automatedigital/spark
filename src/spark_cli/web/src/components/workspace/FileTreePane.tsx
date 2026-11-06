import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Download,
  Eye,
  File,
  FilePlus,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  Loader2,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { api, workspaceRawFileUrl } from "@/lib/api";
import type { FileTreeNode as WorkspaceFileNode } from "@/lib/api_filetree";
import { readDirectory, type DirectoryPage } from "@/lib/api_filetree";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useEventBus } from "@/hooks/useEventBus";
import type { SparkEventEnvelope } from "@/hooks/useEventBus";

// ── File utilities ─────────────────────────────────────────────────────────────

export function FileIcon({ name }: { name: string }) {
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
  onRename,
  expanded,
  onToggleExpand,
  forceExpand,
  slug,
  pages,
  loadPage,
}: {
  node: WorkspaceFileNode;
  depth: number;
  onSelect: (node: WorkspaceFileNode) => void;
  selectedPath: string | null;
  onDelete: (node: WorkspaceFileNode) => void;
  onRename: (node: WorkspaceFileNode, nextName: string) => void;
  expanded: Set<string>;
  onToggleExpand: (path: string) => void;
  forceExpand: boolean;
  slug: string;
  pages: Record<string, DirectoryPage>;
  loadPage: (path: string, more?: boolean) => void;
}) {
  const isDir = node.type === "dir";
  const isSelected = node.path === selectedPath;
  const isExpanded = forceExpand || expanded.has(node.path);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [renameValue, setRenameValue] = useState<string | null>(null);

  const submitRename = () => {
    const next = renameValue?.trim();
    setRenameValue(null);
    if (next && next !== node.name) onRename(node, next);
  };

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
          if (renameValue !== null) return;
          if (isDir) onToggleExpand(node.path);
          else onSelect(node);
        }}
      >
        {isDir ? (
          <>
            <span className="text-muted-foreground/60">
              {isExpanded ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
            </span>
            {isExpanded ? (
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
        {renameValue !== null ? (
          <input
            autoFocus
            value={renameValue}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => setRenameValue(e.target.value)}
            onBlur={submitRename}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Enter") submitRename();
              if (e.key === "Escape") setRenameValue(null);
            }}
            className="min-w-0 flex-1 rounded-sm border border-primary/50 bg-background px-1 py-0 font-mono-ui text-[11px] text-foreground outline-none"
          />
        ) : (
          <span className="flex-1 truncate" title={node.symlink ? "Symbolic link (not expanded)" : node.path}>{node.name}{node.symlink && " (link)"}</span>
        )}
        {renameValue === null && (confirmDelete ? (
          <div className="ml-1 flex items-center gap-1.5">
            <span className="text-[10px] text-muted-foreground">Delete?</span>
            <button
              type="button"
              className="text-destructive hover:text-destructive"
              title="Confirm delete"
              onClick={(e) => { e.stopPropagation(); setConfirmDelete(false); onDelete(node); }}
            >
              <Check className="h-3 w-3" />
            </button>
            <button
              type="button"
              className="text-muted-foreground/60 hover:text-foreground"
              title="Cancel"
              onClick={(e) => { e.stopPropagation(); setConfirmDelete(false); }}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        ) : (
          <div className="ml-1 hidden items-center gap-1.5 group-hover:flex">
            <button
              type="button"
              title="Rename"
              className="text-muted-foreground/50 hover:text-foreground"
              onClick={(e) => { e.stopPropagation(); setRenameValue(node.name); }}
            >
              <Pencil className="h-3 w-3" />
            </button>
            {!isDir && (
              <a
                href={workspaceRawFileUrl(slug, node.path)}
                download={node.name}
                onClick={(e) => e.stopPropagation()}
                title="Download"
                className="text-muted-foreground/50 hover:text-foreground"
              >
                <Download className="h-3 w-3" />
              </a>
            )}
            <button
              type="button"
              className="text-muted-foreground/50 hover:text-destructive"
              title="Delete"
              onClick={(e) => { e.stopPropagation(); setConfirmDelete(true); }}
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
        ))}
      </div>
      {isDir && isExpanded && node.children && (
        <div>
          {node.children.map((child) => (
            <FileNodeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              onSelect={onSelect}
              selectedPath={selectedPath}
              onDelete={onDelete}
              onRename={onRename}
              expanded={expanded}
              onToggleExpand={onToggleExpand}
              forceExpand={forceExpand}
              slug={slug}
              pages={pages}
              loadPage={loadPage}
            />
          ))}
          {pages[node.path]?.next_cursor && <button className="px-4 text-xs text-primary" onClick={() => loadPage(node.path, true)}>Load more in {node.name}</button>}
          {node.children.length === 0 && (
            <div
              className="px-2 py-0.5 text-[11px] italic text-muted-foreground/40"
              style={{ paddingLeft: `${8 + (depth + 1) * 12}px` }}
            >
              {pages[node.path] ? "empty" : "Loading…"}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── FileTreePane ───────────────────────────────────────────────────────────────

const EXPANDED_KEY_PREFIX = "spark-files-expanded:";

export function FileTreePane({
  slug,
  activePath,
  onOpenFile,
}: {
  slug: string;
  activePath: string | null;
  onOpenFile: (node: WorkspaceFileNode) => void;
}) {
  const [pages, setPages] = useState<Record<string, DirectoryPage>>({});
  const pagesRef = useRef(pages);
  pagesRef.current = pages;
  const generation = useRef(0);
  const controllers = useRef(new Map<string, AbortController>());
  const [error, setError] = useState("");
  const [matches, setMatches] = useState<WorkspaceFileNode[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchMore, setSearchMore] = useState(false);
  const searchQueue = useRef<Array<{ path: string; cursor: string }>>([]);
  const searchController = useRef<AbortController | null>(null);
  const [loadingTree, setLoadingTree] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const scopeRef = useRef("");
  scopeRef.current = `${slug}:${showHidden}`;
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [creating, setCreating] = useState<"file" | "dir" | null>(null);
  const [createName, setCreateName] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const reloadTimerRef = useRef<number | null>(null);

  // Restore persisted expansion when the workspace changes.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(EXPANDED_KEY_PREFIX + slug);
      setExpanded(new Set(raw ? (JSON.parse(raw) as string[]) : []));
    } catch {
      setExpanded(new Set());
    }
    setFilter("");
  }, [slug]);

  const loadPage = useCallback(async (path: string, more = false, force = false) => {
    if (scopeRef.current !== `${slug}:${showHidden}`) return;
    const owner = generation.current;
    const previousController = controllers.current.get(path);
    if (previousController && !force) return;
    previousController?.abort();
    const controller = new AbortController();
    controllers.current.set(path, controller);
    setLoadingTree(true);
    setError("");
    try {
      const previous = pagesRef.current[path];
      const result = await readDirectory(slug, path, showHidden, controller.signal,
        more ? previous?.next_cursor ?? "" : "");
      if (owner !== generation.current || controller.signal.aborted) return;
      setPages(current => ({ ...current, [path]: {
        ...result, entries: more && previous?.revision === result.revision
          ? [...previous.entries, ...result.entries] : result.entries,
      } }));
    } catch (cause) {
      if (owner === generation.current && !controller.signal.aborted) setError(String(cause));
    } finally {
      if (controllers.current.get(path) === controller) controllers.current.delete(path);
      if (owner === generation.current) setLoadingTree(controllers.current.size > 0);
    }
  }, [slug, showHidden]);

  const toggleExpand = useCallback((path: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      localStorage.setItem(EXPANDED_KEY_PREFIX + slug, JSON.stringify([...next]));
      return next;
    });
    if (!pagesRef.current[path]) void loadPage(path);
  }, [slug, loadPage]);

  const loadTree = useCallback((affected?: string, removed = false) => {
    const paths = Object.keys(pagesRef.current);
    const invalid = (path: string) => affected === undefined || path === "" ||
      affected.startsWith(`${path}/`) || path === affected || path.startsWith(`${affected}/`);
    const retired = (path: string) => removed && (path === affected || path.startsWith(`${affected}/`));
    if (removed) {
      setExpanded(current => {
        const next = new Set([...current].filter(path => !retired(path)));
        localStorage.setItem(EXPANDED_KEY_PREFIX + slug, JSON.stringify([...next]));
        return next;
      });
    }
    for (const [path, controller] of controllers.current) {
      if (invalid(path) && (retired(path) || (path !== "" && !expanded.has(path)))) {
        controller.abort();
        controllers.current.delete(path);
      }
    }
    setPages(current => Object.fromEntries(Object.entries(current).filter(([path]) =>
      !retired(path) && (!invalid(path) || path === "" || expanded.has(path)))));
    for (const path of new Set(["", ...paths])) {
      if (!retired(path) && invalid(path) && (path === "" || expanded.has(path))) void loadPage(path, false, true);
    }
  }, [loadPage, expanded, slug]);

  useEffect(() => {
    const ownedControllers = controllers.current;
    generation.current += 1;
    for (const controller of ownedControllers.values()) controller.abort();
    controllers.current.clear();
    pagesRef.current = {};
    setPages({});
    setError("");
    void loadPage("");
    return () => {
      generation.current += 1;
      for (const controller of ownedControllers.values()) controller.abort();
      ownedControllers.clear();
    };
  }, [loadPage]);

  const runSearch = useCallback(async (controller: AbortController) => {
    setSearching(true);
    try {
      // Yield after twenty bounded pages. Continue is explicit, and every read
      // is abortable when the query or authorised project changes.
      for (let count = 0; count < 20 && searchQueue.current.length; count++) {
        const item = searchQueue.current.shift()!;
        const page = await readDirectory(slug, item.path, showHidden, controller.signal, item.cursor);
        if (controller.signal.aborted) return;
        const found = page.entries.filter(node => node.path.toLowerCase().includes(filter.trim().toLowerCase()));
        if (found.length) setMatches(found);
        for (const node of page.entries) {
          if (node.type === "dir") searchQueue.current.push({ path: node.path, cursor: "" });
        }
        if (page.next_cursor) searchQueue.current.push({ path: item.path, cursor: page.next_cursor });
        if (found.length) break;
      }
      if (!controller.signal.aborted) setSearchMore(searchQueue.current.length > 0);
    } catch (cause) {
      if (!controller.signal.aborted) setError(String(cause));
    } finally {
      if (!controller.signal.aborted) setSearching(false);
    }
  }, [slug, showHidden, filter]);

  useEffect(() => {
    searchController.current?.abort();
    setMatches([]);
    setSearchMore(false);
    setSearching(false);
    if (!filter.trim()) return;
    const controller = new AbortController();
    searchController.current = controller;
    searchQueue.current = [{ path: "", cursor: "" }];
    const timer = window.setTimeout(() => void runSearch(controller), 200);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [runSearch, filter]);

  useEffect(() => {
    for (const path of expanded) {
      if (!pages[path]) {
        const parent = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
        if (pages[parent]?.entries.some(node => node.path === path && node.type === "dir")) void loadPage(path);
      }
    }
  }, [expanded, pages, loadPage]);

  // Live refresh: the agent writes files outside the UI, so reload (debounced)
  // when a turn finishes or the server signals a workspace file change.
  useEventBus((env: SparkEventEnvelope) => {
    if (env.topic !== "chat.turn_done" && env.topic !== "workspace.files.changed") return;
    if (typeof env.payload.slug === "string" && env.payload.slug !== slug) return;
    const affected = typeof env.payload.path === "string" ? env.payload.path : undefined;
    if (reloadTimerRef.current !== null) window.clearTimeout(reloadTimerRef.current);
    reloadTimerRef.current = window.setTimeout(() => { loadTree(affected); }, 400);
  });

  useEffect(() => () => {
    if (reloadTimerRef.current !== null) window.clearTimeout(reloadTimerRef.current);
  }, []);

  const handleDelete = async (node: WorkspaceFileNode) => {
    try {
      await api.deleteWorkspaceFile(slug, node.path);
      loadTree(node.path, true);
    } catch (e) {
      console.error("Delete failed", e);
    }
  };

  const handleRename = async (node: WorkspaceFileNode, nextName: string) => {
    const parent = node.path.includes("/") ? node.path.slice(0, node.path.lastIndexOf("/") + 1) : "";
    try {
      await api.renameWorkspacePath(slug, node.path, parent + nextName);
      loadTree(node.path, true);
    } catch (e) {
      console.error("Rename failed", e);
    }
  };

  const submitCreate = async () => {
    const name = createName.trim();
    const kind = creating;
    setCreating(null);
    setCreateName("");
    if (!name || !kind) return;
    try {
      if (kind === "file") await api.writeWorkspaceFile(slug, name, "");
      else await api.makeWorkspaceDir(slug, name);
      loadTree(name);
    } catch (e) {
      console.error("Create failed", e);
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

  const tree = pages[""]?.entries ?? [];
  const visibleTree = useMemo(() => {
    const build = (nodes: WorkspaceFileNode[]): WorkspaceFileNode[] => nodes.map(node =>
      node.type === "dir" ? { ...node, children: expanded.has(node.path)
        ? build(pages[node.path]?.entries ?? []) : [] } : node);
    return build(filter.trim() ? matches : pages[""]?.entries ?? []);
  }, [pages, expanded, filter, matches]);
  const filtering = filter.trim().length > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between border-b border-border px-2 py-1">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground/60">Explorer</span>
        <div className="flex items-center gap-1">
          {uploading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
          <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="New file" onClick={() => { setCreating("file"); setCreateName(""); }}>
            <FilePlus className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="New folder" onClick={() => { setCreating("dir"); setCreateName(""); }}>
            <FolderPlus className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="Upload files" onClick={() => fileInputRef.current?.click()}>
            <Upload className="h-3.5 w-3.5" />
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className={cn("h-6 w-6 p-0", showHidden && "bg-secondary text-foreground")}
            title={showHidden ? "Hide hidden files" : "Show hidden files"}
            aria-pressed={showHidden}
            onClick={() => setShowHidden((v) => !v)}
          >
            <Eye className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" variant="ghost" className="h-6 w-6 p-0" title="Refresh" onClick={() => void loadTree()}>
            <RefreshCw className={cn("h-3.5 w-3.5", loadingTree && "animate-spin")} />
          </Button>
        </div>
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={(e) => e.target.files && void handleUpload(e.target.files)} />
      </div>

      {/* Filter box */}
      <div className="flex shrink-0 items-center gap-1.5 border-b border-border px-2 py-1">
        <Search className="h-3 w-3 shrink-0 text-muted-foreground/50" />
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") setFilter(""); }}
          placeholder="Filter files…"
          className="h-5 w-full bg-transparent text-[11px] text-foreground outline-none placeholder:text-muted-foreground/40"
        />
        {filter && (
          <button type="button" className="text-muted-foreground/50 hover:text-foreground" title="Clear" onClick={() => setFilter("")}>
            <X className="h-3 w-3" />
          </button>
        )}
      </div>

      {/* New file/folder inline input */}
      {creating && (
        <div className="flex shrink-0 items-center gap-1.5 border-b border-border bg-background/60 px-2 py-1">
          {creating === "file" ? <FilePlus className="h-3 w-3 text-sky-300/70" /> : <FolderPlus className="h-3 w-3 text-amber-300/80" />}
          <input
            autoFocus
            value={createName}
            onChange={(e) => setCreateName(e.target.value)}
            onBlur={() => void submitCreate()}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submitCreate();
              if (e.key === "Escape") { setCreating(null); setCreateName(""); }
            }}
            placeholder={creating === "file" ? "path/to/file.txt" : "path/to/folder"}
            className="h-5 w-full rounded-sm border border-primary/40 bg-background px-1 font-mono-ui text-[11px] text-foreground outline-none"
          />
        </div>
      )}

      <div
        className={cn("min-h-0 flex-1 overflow-y-auto py-1 transition-all", dragOver && "bg-primary/5 ring-2 ring-inset ring-primary/20")}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files.length) void handleUpload(e.dataTransfer.files); }}
      >
        {error && <div role="alert" className="p-2 text-xs text-destructive">{error}</div>}
        {filtering && <div className="p-2 text-xs text-muted-foreground">{searching ? "Searching…" : searchMore ? "More folders remain." : "Search complete."}
          {searchMore && !searching && <button onClick={() => { const controller = searchController.current; if (controller) void runSearch(controller); }}>Continue search</button>}
        </div>}
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
        {tree.length > 0 && filtering && visibleTree.length === 0 && (
          <div className="py-8 text-center text-xs text-muted-foreground/50">No matches.</div>
        )}
        {visibleTree.map((node) => (
          <FileNodeRow
            key={node.path}
            node={node}
            depth={0}
            onSelect={onOpenFile}
            selectedPath={activePath}
            onDelete={(n) => void handleDelete(n)}
            onRename={(n, name) => void handleRename(n, name)}
            expanded={expanded}
            onToggleExpand={toggleExpand}
            forceExpand={false}
            pages={pages}
            loadPage={(path, more) => void loadPage(path, more)}
            slug={slug}
          />
        ))}
        {!filtering && pages[""]?.next_cursor && <button className="p-2 text-xs text-primary" onClick={() => void loadPage("", true)}>Load more files</button>}
      </div>
    </div>
  );
}
