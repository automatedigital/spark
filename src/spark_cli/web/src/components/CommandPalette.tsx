import { useEffect, useMemo, useRef, useState } from "react";
import { Search, LayoutGrid, MessageSquare, Clock, Package, Settings, FolderOpen, ListTodo, Loader2, Square, Brain } from "lucide-react";
import { api } from "@/lib/api";
import type { CronJob, KanbanTaskRow, SessionInfo, SkillInfo, WorkspaceProject } from "@/lib/api";
import { setGlobalNavTarget } from "@/lib/globalNavigation";
import { cn } from "@/lib/utils";
import { threadTitle } from "@/components/chat/ThreadRow";

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

const PAGE_ITEMS = [
  { id: "chat", label: "Chat", description: "Projects and conversations", icon: MessageSquare },
  { id: "files", label: "Files", description: "Workspace files", icon: FolderOpen },
  { id: "canvas", label: "Canvas", description: "Visual board", icon: Square },
  { id: "kanban", label: "Tasks", description: "Task board", icon: LayoutGrid },
  { id: "cron", label: "Schedule", description: "Scheduled jobs", icon: Clock },
  { id: "skills", label: "Skills", description: "Skill manager", icon: Package },
  { id: "memory", label: "Memory", description: "What the agent remembers", icon: Brain },
];

export function CommandPalette({ open, onClose, onNavigate, onOpenSettings }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const [activeIdx, setActiveIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [tasks, setTasks] = useState<KanbanTaskRow[]>([]);
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [skills, setSkills] = useState<SkillInfo[]>([]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIdx(0);
      setTimeout(() => inputRef.current?.focus(), 10);
      setLoading(true);
      Promise.allSettled([
        api.listWorkspaceProjects(),
        api.getSessions(500, 0),
        api.getKanbanBoard({ board: "default", tenant: null, assignee: null, q: null }),
        api.getCronJobs(),
        api.getSkills(),
      ]).then(([projectRes, sessionRes, taskRes, jobRes, skillRes]) => {
        if (projectRes.status === "fulfilled") setProjects(projectRes.value.projects);
        if (sessionRes.status === "fulfilled") setSessions(sessionRes.value.sessions);
        if (taskRes.status === "fulfilled") {
          setTasks(Object.values(taskRes.value.columns).flat());
        }
        if (jobRes.status === "fulfilled") setJobs(jobRes.value);
        if (skillRes.status === "fulfilled") setSkills(skillRes.value);
      }).finally(() => setLoading(false));
    }
  }, [open]);

  const allItems: CommandItem[] = useMemo(() => [
    ...projects.map((project) => ({
      id: `project:${project.slug}`,
      label: project.name,
      description: project.path,
      group: "Projects",
      icon: FolderOpen,
      action: () => {
        setGlobalNavTarget({ type: "project", id: project.slug });
        onNavigate("chat");
        onClose();
      },
    })),
    ...sessions.map((session) => ({
      id: `thread:${session.id}`,
      label: threadTitle(session),
      description: session.preview ?? session.model ?? session.id,
      group: "Chat Threads",
      icon: MessageSquare,
      action: () => {
        setGlobalNavTarget({ type: "thread", id: session.id });
        onNavigate("chat");
        onClose();
      },
    })),
    ...tasks.map((task) => ({
      id: `task:${task.id}`,
      label: task.title,
      description: [task.status, task.assignee, task.tenant].filter(Boolean).join(" · ") || task.id,
      group: "Tasks",
      icon: ListTodo,
      action: () => {
        setGlobalNavTarget({ type: "task", id: task.id });
        onNavigate("kanban");
        onClose();
      },
    })),
    ...jobs.map((job) => ({
      id: `scheduled-task:${job.id}`,
      label: job.name || job.prompt.slice(0, 80),
      description: `${job.state} · ${job.schedule_display || job.schedule?.display || job.schedule?.expr}`,
      group: "Scheduled Tasks",
      icon: Clock,
      action: () => {
        setGlobalNavTarget({ type: "scheduled-task", id: job.id });
        onNavigate("cron");
        onClose();
      },
    })),
    ...skills.map((skill) => ({
      id: `skill:${skill.name}`,
      label: skill.name,
      description: skill.description || skill.category,
      group: "Skills",
      icon: Package,
      action: () => {
        setGlobalNavTarget({ type: "skill", id: skill.name });
        onNavigate("skills");
        onClose();
      },
    })),
    ...PAGE_ITEMS.map((p) => ({
      ...p,
      group: "Pages",
      action: () => { onNavigate(p.id); onClose(); },
    })),
    {
      id: "settings",
      label: "Settings",
      description: "App preferences and configuration",
      group: "Pages",
      icon: Settings,
      action: () => { onOpenSettings(); onClose(); },
    },
  ], [jobs, onClose, onNavigate, onOpenSettings, projects, sessions, skills, tasks]);

  const filtered = query.trim()
    ? allItems.filter((item) => {
        const q = query.toLowerCase();
        return item.label.toLowerCase().includes(q) ||
          item.group.toLowerCase().includes(q) ||
          (item.description?.toLowerCase().includes(q));
      })
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
            placeholder="Search projects, threads, tasks, schedules, skills…"
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
                  onMouseEnter={() => setActiveIdx(i)}
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
