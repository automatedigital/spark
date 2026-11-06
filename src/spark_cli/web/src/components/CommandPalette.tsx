import { PAGE_DESTINATIONS, SETTINGS_SECTIONS } from "@/lib/settingsRegistry";
import { useEffect, useMemo, useRef, useState } from "react";
import { Search, MessageSquare, Clock, Package, Plug, Settings, FolderOpen, Loader2 } from "lucide-react";
import { cachedPaletteRecent, paletteCategories, paletteItemKey, paletteScope, readPalette, type PaletteCategory, type PaletteItem, type PalettePage } from "@/lib/paletteClient";
import { SIDEBAR_SCOPE_EVENT, sidebarPreferenceScopeReady } from "@/lib/sidebarPrefs";
import { setGlobalNavTarget } from "@/lib/globalNavigation";
import { cn } from "@/lib/utils";

interface CommandItem {
  id: string;
  label: string;
  description?: string;
  group: string;
  icon: React.FC<{ className?: string }>;
  action: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onNavigate: (page: string) => void;
  onOpenSettings: () => void;
}

const PAGE_ICONS = { chat: MessageSquare, files: FolderOpen, cron: Clock, skills: Package, connectors: Plug };
const PAGE_ITEMS = [
  ...PAGE_DESTINATIONS.map((item) => ({ ...item, icon: PAGE_ICONS[item.id] })),
  ...SETTINGS_SECTIONS.filter((item) => "common" in item && !("desktopOnly" in item)).map((item) => ({
    id: `settings:${item.id}`, destination: item.id, label: item.label, description: `Settings › ${item.label}`, icon: Settings,
  })),
];

export function CommandPalette({ open, onClose, onNavigate, onOpenSettings }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [scope, setScope] = useState(paletteScope);
  const [recent, setRecent] = useState(() => cachedPaletteRecent());
  const [pages, setPages] = useState<Partial<Record<PaletteCategory, PalettePage>>>({});
  const [errors, setErrors] = useState<string[]>([]);
  const [pending, setPending] = useState(0);
  const [dataIdentity, setDataIdentity] = useState(() => `${scope}:`);
  const dataCurrent = dataIdentity === `${scope}:${query}` && scope === paletteScope();
  const owner = useRef<{ current: () => boolean; controller: AbortController } | null>(null);
  const loading = dataCurrent && pending > 0;

  useEffect(() => {
    const changed = () => setScope(paletteScope());
    window.addEventListener(SIDEBAR_SCOPE_EVENT, changed);
    window.addEventListener("storage", changed);
    const timer = window.setInterval(changed, 50);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener(SIDEBAR_SCOPE_EVENT, changed);
      window.removeEventListener("storage", changed);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveId(null);
    inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    const current = () => live && !controller.signal.aborted && scope === paletteScope();
    owner.current = { current, controller };
    setDataIdentity(`${scope}:${query}`);
    setPages({});
    setErrors([]);
    setPending(0);
    const cached = cachedPaletteRecent();
    setRecent(cached);
    const run = (category: PaletteCategory | "recent") => {
      setPending((n) => n + 1);
      readPalette(category, query.trim(), controller.signal).then((page) => {
        if (!current()) return;
        if (category === "recent") setRecent(page);
        else setPages((old) => ({ ...old, [category]: page }));
      }).catch(() => {
        if (current()) setErrors((old) => [...old, category]);
      }).finally(() => {
        if (current()) setPending((n) => n - 1);
      });
    };
    let timer: number | undefined;
    if (open && sidebarPreferenceScopeReady() && query.trim()) {
      timer = window.setTimeout(() => paletteCategories.forEach(run), 150);
    } else if (open && sidebarPreferenceScopeReady() && !cached) run("recent");
    return () => { live = false; controller.abort(); window.clearTimeout(timer); };
  }, [open, query, scope]);

  const loadMore = (category: PaletteCategory, offset: number) => {
    const request = owner.current;
    if (!request?.current()) return;
    setPending((n) => n + 1);
    readPalette(category, query.trim(), request.controller.signal, offset).then((page) => {
      if (request.current()) setPages((old) => ({ ...old, [category]: { ...page, items: page.items } }));
    }).catch(() => {
      if (request.current()) setErrors((old) => [...new Set([...old, category])]);
    }).finally(() => {
      if (request.current()) setPending((n) => n - 1);
    });
  };

  const allItems: CommandItem[] = useMemo(() => {
    const staticItems = [
      ...PAGE_ITEMS.map((p) => ({ ...p, group: "Pages", action: () => { onNavigate("destination" in p ? p.destination : p.id); onClose(); } })),
      { id: "settings", label: "Settings", description: "App preferences and configuration", group: "Pages", icon: Settings, action: () => { onOpenSettings(); onClose(); } },
    ];
    const groups = { thread: "Chat Threads", message: "Messages", project: "Projects", "scheduled-task": "Scheduled Tasks", skill: "Skills" };
    const icons = { thread: MessageSquare, message: MessageSquare, project: FolderOpen, "scheduled-task": Clock, skill: Package };
    const items: PaletteItem[] = !dataCurrent ? [] : query.trim()
      ? paletteCategories.flatMap((category) => pages[category]?.items ?? [])
      : recent?.items ?? [];
    return [...staticItems, ...items.map((item) => ({
      id: paletteItemKey(item), label: item.label, description: item.description,
      group: groups[item.kind], icon: icons[item.kind],
      action: () => {
        if (scope !== paletteScope()) return;
        setGlobalNavTarget({ type: item.kind === "message" ? "thread" : item.kind, id: item.destination ?? item.id, ...(item.kind === "message" ? { messageId: item.id } : {}) });
        onNavigate(item.kind === "skill" ? "skills" : item.kind === "scheduled-task" ? "cron" : "chat");
        onClose();
      },
    }))];
  }, [onClose, onNavigate, onOpenSettings, pages, query, recent, scope, dataCurrent]);

  const filtered = allItems.filter((item) => {
    if (!query.trim() || item.group !== "Pages") return true;
    const q = query.trim().toLowerCase();
    return `${item.label} ${item.description} ${item.group}`.toLowerCase().includes(q);
  });
  const activeIdx = Math.max(0, filtered.findIndex((item) => item.id === activeId));

  useEffect(() => {
    if (!activeId) return;
    const selected = document.getElementById(`command-palette-item-${activeId}`);
    if (selected && listRef.current?.contains(selected)) selected.scrollIntoView({ block: "nearest" });
  }, [activeId, activeIdx]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveId(filtered[Math.min(activeIdx + 1, filtered.length - 1)]?.id ?? null);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveId(filtered[Math.max(activeIdx - 1, 0)]?.id ?? null);
    } else if (e.key === "Enter") {
      filtered[activeIdx]?.action();
    } else if (e.key === "Escape") {
      onClose();
    }
  };

  useEffect(() => {
    setActiveId(null);
  }, [query]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] bg-background/60 backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="presentation"
    >
      <div
        className="w-full max-w-lg rounded-xl border border-border bg-popover shadow-2xl overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onKeyDown={handleKeyDown}
      >
        <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
          <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          <input
            ref={inputRef}
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            placeholder="Search projects, threads, schedules, skills…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            role="combobox"
            aria-expanded="true"
            aria-controls="command-palette-results"
            aria-activedescendant={filtered[activeIdx] ? `command-palette-item-${filtered[activeIdx].id}` : undefined}
          />
          {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
          <kbd className="text-[10px] text-muted-foreground border border-border rounded px-1 py-0.5">Esc</kbd>
        </div>

        {filtered.length === 0 ? (
          <div className="px-4 py-6 text-center text-sm text-muted-foreground">No results</div>
        ) : (
          <ul
            id="command-palette-results"
            ref={listRef}
            className="py-1 max-h-72 overflow-y-auto"
            role="listbox"
            aria-label="Command results"
          >
            {filtered.map((item, i) => (
              <li key={item.id} role="presentation">
                <button
                  id={`command-palette-item-${item.id}`}
                  role="option"
                  aria-selected={i === activeIdx}
                  className={cn(
                    "flex w-full items-center gap-3 px-4 py-2.5 text-left text-sm hover:bg-accent/50 transition-colors",
                    i === activeIdx && "bg-accent/50"
                  )}
                  onMouseEnter={() => setActiveId(item.id)}
                  onClick={item.action}
                >
                  <item.icon className="h-4 w-4 text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <div className="font-medium truncate">{item.label}</div>
                      <span className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                        {item.group}
                      </span>
                    </div>
                    {item.description && (
                      <div className="text-xs text-muted-foreground truncate">{item.description}</div>
                    )}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}

        {dataCurrent && errors.length > 0 && <div role="status" className="px-4 py-2 text-xs text-muted-foreground">Could not load: {[...new Set(errors)].join(", ")}. Other results remain available.</div>}
        {dataCurrent && query.trim() && paletteCategories.map((category) => pages[category]?.next != null && (
          <button key={category} disabled={loading} className="px-4 py-2 text-xs" onClick={() => loadMore(category, pages[category]!.next!)}>More {category}</button>
        ))}

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
