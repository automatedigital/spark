import { useCallback, useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  Download,
  Eye,
  File,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
  Trash2,
  Upload,
} from "lucide-react";
import { api, workspaceRawFileUrl } from "@/lib/api";
import type { WorkspaceFileNode } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

// ── File utilities ─────────────────────────────────────────────────────────────

export function getFileCategory(mime: string, filename: string): "text" | "image" | "video" | "binary" {
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
  slug,
}: {
  node: WorkspaceFileNode;
  depth: number;
  onSelect: (node: WorkspaceFileNode) => void;
  selectedPath: string | null;
  onDelete: (node: WorkspaceFileNode) => void;
  slug: string;
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
          <div className="ml-1 hidden items-center gap-1.5 group-hover:flex">
            <a
              href={workspaceRawFileUrl(slug, node.path)}
              download={node.name}
              onClick={(e) => e.stopPropagation()}
              title="Download"
              className="text-muted-foreground/50 hover:text-foreground"
            >
              <Download className="h-3 w-3" />
            </a>
            <button
              type="button"
              className="text-muted-foreground/50 hover:text-destructive"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(node);
              }}
            >
              <Trash2 className="h-3 w-3" />
            </button>
          </div>
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
              slug={slug}
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

// ── FileTreePane ───────────────────────────────────────────────────────────────

export function FileTreePane({
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
  const [showHidden, setShowHidden] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadTree = useCallback(async () => {
    setLoadingTree(true);
    try {
      const res = await api.getWorkspaceFileTree(slug, showHidden);
      setTree(res.tree);
    } catch (e) {
      console.error("Tree load failed", e);
    } finally {
      setLoadingTree(false);
    }
  }, [slug, showHidden]);

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
            slug={slug}
          />
        ))}
      </div>
    </div>
  );
}
