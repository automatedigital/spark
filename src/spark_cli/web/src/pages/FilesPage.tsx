import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  File,
  FileText,
  Folder,
  FolderOpen,
  GripVertical,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import ReactCodeMirror, { keymap } from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { markdown } from "@codemirror/lang-markdown";
import { json } from "@codemirror/lang-json";
import { html } from "@codemirror/lang-html";
import { css } from "@codemirror/lang-css";
import { sql } from "@codemirror/lang-sql";
import { rust } from "@codemirror/lang-rust";
import { go } from "@codemirror/lang-go";
import { java } from "@codemirror/lang-java";
import { cpp } from "@codemirror/lang-cpp";
import { xml } from "@codemirror/lang-xml";
import { StreamLanguage } from "@codemirror/language";
import { shell } from "@codemirror/legacy-modes/mode/shell";
import { yaml } from "@codemirror/legacy-modes/mode/yaml";
import { toml } from "@codemirror/legacy-modes/mode/toml";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView } from "@codemirror/view";
import { api, mediaFileUrl } from "@/lib/api";
import type { FileListEntry } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// Layout + background overrides — syntax colors come from oneDark, background matches app UI
const cmLayout = [
  EditorView.theme({
    "&": { height: "100%", fontSize: "0.72rem" },
    ".cm-scroller": { fontFamily: "var(--font-mono-ui, monospace)", lineHeight: "1.25rem", overflow: "auto" },
    ".cm-content": { padding: "0.75rem 0" },
    ".cm-line": { padding: "0 1rem" },
    ".cm-gutters": { minWidth: "2.5rem", borderRight: "1px solid rgba(255,255,255,0.06)" },
    ".cm-activeLine": { background: "rgba(255,255,255,0.03)" },
    ".cm-activeLineGutter": { background: "rgba(255,255,255,0.03)" },
  }),
  // Force background transparent so the app's surface shows through
  EditorView.theme({
    "&, &.cm-focused": { background: "transparent !important" },
    ".cm-editor, .cm-wrap": { background: "transparent !important" },
    ".cm-scroller": { background: "transparent !important" },
    ".cm-content": { background: "transparent !important" },
    ".cm-gutters": { background: "transparent !important" },
  }, { dark: true }),
];

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

const ROOT_PATH = ".";

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

function extensionFor(name: string) {
  const ext = extOf(name);
  switch (ext) {
    case "py": return python();
    case "js": case "jsx": return javascript({ jsx: true });
    case "ts": case "tsx": return javascript({ typescript: true, jsx: ext === "tsx" });
    case "md": return markdown();
    case "json": return json();
    case "html": return html();
    case "css": return css();
    case "sql": return sql();
    case "rs": return rust();
    case "go": return go();
    case "java": return java();
    case "c": case "cpp": case "h": return cpp();
    case "xml": case "svg": return xml();
    case "sh": case "bash": return StreamLanguage.define(shell);
    case "yaml": case "yml": return StreamLanguage.define(yaml);
    case "toml": case "ini": case "cfg": case "env": return StreamLanguage.define(toml);
    default: return null;
  }
}

function CodeEditor({
  file,
  onChange,
  onSave,
}: {
  file: OpenFile;
  onChange: (content: string) => void;
  onSave: () => void;
}) {
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;

  const extensions = useMemo(() => {
    const langExt = extensionFor(file.name);
    const saveBinding = keymap.of([{
      key: "Mod-s",
      run: () => { onSaveRef.current(); return true; },
    }]);
    return langExt ? [saveBinding, langExt, ...cmLayout] : [saveBinding, ...cmLayout];
  }, [file.name]);

  return (
    <ReactCodeMirror
      value={file.content ?? ""}
      onChange={onChange}
      theme={oneDark}
      extensions={extensions}
      basicSetup={{
        lineNumbers: true,
        foldGutter: false,
        dropCursor: false,
        allowMultipleSelections: true,
        indentOnInput: true,
        bracketMatching: true,
        closeBrackets: true,
        autocompletion: false,
        rectangularSelection: false,
        crosshairCursor: false,
        highlightActiveLine: true,
        highlightSelectionMatches: true,
        closeBracketsKeymap: false,
        searchKeymap: false,
        foldKeymap: false,
        completionKeymap: false,
        lintKeymap: false,
      }}
      style={{ height: "100%" }}
    />
  );
}

// ── File browser panel ─────────────────────────────────────────────────────────

function FileBrowser({
  currentPath,
  selectedFile,
  onNavigate,
  onSelectFile,
  onRefresh,
}: {
  currentPath: string;
  selectedFile: string | null;
  onNavigate: (path: string) => void;
  onSelectFile: (entry: FileListEntry) => void;
  onRefresh: () => void;
}) {
  const [entries, setEntries] = useState<FileListEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQ, setSearchQ] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.listChatFiles(currentPath);
      setEntries(res.entries);
    } catch (e) {
      console.error("Failed to list files", e);
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [currentPath]);

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

  const canGoUp = currentPath !== ROOT_PATH;
  const visible = searchQ.trim()
    ? entries.filter((e) => e.name.toLowerCase().includes(searchQ.toLowerCase()))
    : entries;
  const dirs = visible.filter((e) => e.type === "dir");
  const files = visible.filter((e) => e.type !== "dir");

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

        {/* Directories */}
        {dirs.map((entry) => (
          <div
            key={entry.path}
            className="spark-list-row group flex cursor-pointer items-center gap-2 px-3 py-2 text-sm text-muted-foreground hover:bg-secondary hover:text-foreground transition select-none"
            onClick={() => onNavigate(entry.path)}
          >
            <FolderOpen className="h-4 w-4 shrink-0 text-amber-300/80" />
            <span className="flex-1 truncate">{entry.name}</span>
            <ChevronRight className="h-3.5 w-3.5 opacity-30 group-hover:opacity-60" />
          </div>
        ))}

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
            <button
              type="button"
              title="Delete"
              className="ml-1 hidden shrink-0 text-muted-foreground/40 hover:text-destructive group-hover:block"
              onClick={(e) => { e.stopPropagation(); setConfirmDelete(entry.path); }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}

        {!loading && visible.length === 0 && entries.length > 0 && (
          <div className="py-8 text-center text-xs text-muted-foreground/60">No matches</div>
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

  const handleSelectFile = async (entry: FileListEntry) => {
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
  };

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
                    <CodeEditor
                      file={selectedFile}
                      onChange={handleContentChange}
                      onSave={handleSave}
                    />
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
