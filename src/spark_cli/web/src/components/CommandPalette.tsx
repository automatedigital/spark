import { useEffect, useRef, useState } from "react";
import { Search, LayoutGrid, MessageSquare, Clock, Package, Settings } from "lucide-react";
import { cn } from "@/lib/utils";

interface CommandItem {
  id: string;
  label: string;
  description?: string;
  icon: React.FC<{ className?: string }>;
  action: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onNavigate: (page: string) => void;
  onOpenSettings: () => void;
}

const PAGE_ITEMS = [
  { id: "chat", label: "Chat", description: "Projects and conversations", icon: MessageSquare },
  { id: "kanban", label: "Tasks", description: "Task board", icon: LayoutGrid },
  { id: "cron", label: "Schedule", description: "Scheduled jobs", icon: Clock },
  { id: "skills", label: "Skills", description: "Skill manager", icon: Package },
];

export function CommandPalette({ open, onClose, onNavigate, onOpenSettings }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [activeIdx, setActiveIdx] = useState(0);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIdx(0);
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [open]);

  const allItems: CommandItem[] = [
    ...PAGE_ITEMS.map((p) => ({
      ...p,
      action: () => { onNavigate(p.id); onClose(); },
    })),
    {
      id: "settings",
      label: "Settings",
      description: "App preferences and configuration",
      icon: Settings,
      action: () => { onOpenSettings(); onClose(); },
    },
  ];

  const filtered = query.trim()
    ? allItems.filter((item) =>
        item.label.toLowerCase().includes(query.toLowerCase()) ||
        (item.description?.toLowerCase().includes(query.toLowerCase()))
      )
    : allItems;

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      filtered[activeIdx]?.action();
    } else if (e.key === "Escape") {
      onClose();
    }
  };

  useEffect(() => {
    setActiveIdx(0);
  }, [query]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] bg-background/60 backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-border bg-popover shadow-2xl overflow-hidden"
        onKeyDown={handleKeyDown}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            placeholder="Navigate to a page or action…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <kbd className="text-[10px] text-muted-foreground border border-border rounded px-1 py-0.5">Esc</kbd>
        </div>

        {filtered.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-muted-foreground">No results</div>
        ) : (
          <ul ref={listRef} className="py-1 max-h-72 overflow-y-auto">
            {filtered.map((item, i) => (
              <li key={item.id}>
                <button
                  className={cn(
                    "flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-accent/50 transition-colors",
                    i === activeIdx && "bg-accent/50"
                  )}
                  onMouseEnter={() => setActiveIdx(i)}
                  onClick={item.action}
                >
                  <item.icon className="h-4 w-4 text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="font-medium">{item.label}</div>
                    {item.description && (
                      <div className="text-xs text-muted-foreground truncate">{item.description}</div>
                    )}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="border-t border-border px-4 py-2 flex items-center gap-4 text-[10px] text-muted-foreground">
          <span><kbd className="border border-border rounded px-1">↑↓</kbd> navigate</span>
          <span><kbd className="border border-border rounded px-1">↵</kbd> select</span>
          <span><kbd className="border border-border rounded px-1">Esc</kbd> close</span>
          <span className="ml-auto"><kbd className="border border-border rounded px-1">⌘K</kbd> toggle</span>
        </div>
      </div>
    </div>
  );
}
