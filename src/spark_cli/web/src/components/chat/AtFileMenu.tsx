import { useEffect, useRef, useState } from "react";
import { File, Folder } from "lucide-react";
import { api } from "@/lib/api";
import type { FileListEntry } from "@/lib/api";

interface AtFileMenuProps {
  query: string;          // text typed after @, e.g. "src/comp" or ""
  workspaceSlug?: string; // present when in workspace context
  onSelect: (path: string, isDir: boolean) => void;
  onClose: () => void;
}

export function AtFileMenu({ query, workspaceSlug, onSelect, onClose }: AtFileMenuProps) {
  const [entries, setEntries] = useState<FileListEntry[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Derive which directory to list and what name prefix to filter by
  const lastSlash = query.lastIndexOf("/");
  const dirPath = lastSlash >= 0 ? query.slice(0, lastSlash) : "";
  const nameFilter = lastSlash >= 0 ? query.slice(lastSlash + 1) : query;

  useEffect(() => {
    const timer = setTimeout(() => {
      const controller = new AbortController();
      if (workspaceSlug) {
        api.listWorkspaceDir(workspaceSlug, dirPath).then((r) => setEntries(r.entries)).catch(() => {});
      } else {
        api.listChatFiles(dirPath).then((r) => setEntries(r.entries)).catch(() => {});
      }
      return () => controller.abort();
    }, 200);
    return () => clearTimeout(timer);
  }, [workspaceSlug, dirPath]);

  const filtered = entries.filter(
    (e) => !nameFilter || e.name.toLowerCase().startsWith(nameFilter.toLowerCase()),
  );

  useEffect(() => setActiveIdx(0), [query]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (filtered.length === 0) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIdx((i) => (i + 1) % filtered.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIdx((i) => (i - 1 + filtered.length) % filtered.length);
      } else if (e.key === "Tab" || e.key === "Enter") {
        e.preventDefault();
        const entry = filtered[activeIdx];
        if (entry) onSelect(entry.path, entry.type === "dir");
      } else if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handler, { capture: true });
    return () => window.removeEventListener("keydown", handler, { capture: true });
  }, [filtered, activeIdx, onSelect, onClose]);

  useEffect(() => {
    const el = containerRef.current?.querySelector(`[data-idx="${activeIdx}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [activeIdx]);

  if (filtered.length === 0) return null;

  return (
    <div
      ref={containerRef}
      className="absolute bottom-full left-4 right-4 mb-1 z-50 rounded-lg border border-border bg-popover shadow-xl max-h-[280px] overflow-y-auto"
    >
      <div className="px-3 py-1 text-[9px] uppercase tracking-widest text-muted-foreground/60 font-semibold border-b border-border/40 sticky top-0 bg-popover">
        {dirPath ? dirPath + "/" : "Files"}
      </div>
      {filtered.map((entry, idx) => {
        const isActive = idx === activeIdx;
        const isDir = entry.type === "dir";
        return (
          <button
            key={entry.path}
            type="button"
            data-idx={idx}
            className={`w-full flex items-center gap-3 px-3 py-1.5 text-left transition-colors ${
              isActive ? "bg-primary/10 text-foreground" : "hover:bg-secondary/60 text-foreground/90"
            }`}
            onClick={() => onSelect(entry.path, isDir)}
            onMouseEnter={() => setActiveIdx(idx)}
          >
            {isDir ? (
              <Folder className="h-3.5 w-3.5 shrink-0 text-primary" />
            ) : (
              <File className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            )}
            <span className="font-mono text-xs text-primary shrink-0">
              {entry.name}{isDir ? "/" : ""}
            </span>
            <span className="text-xs text-muted-foreground truncate flex-1">{entry.path}</span>
          </button>
        );
      })}
    </div>
  );
}
