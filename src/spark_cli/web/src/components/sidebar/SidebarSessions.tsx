/**
 * Global-sidebar session navigator: search, PINNED section and SESSIONS
 * grouped by workspace project. Hermes-style layout; backed by the shared
 * session store.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  ChevronRight,
  FolderOpen,
  Loader2,
  MessageSquare,
  Pin,
  Plus,
  Search,
  Trash2,
  X,
} from "lucide-react";
import type { SessionInfo, WorkspaceProject } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { threadTitle } from "@/components/chat/ThreadRow";
import { useSessionStore, slugFromSource } from "@/lib/sessionStore";

// ── SessionRow ────────────────────────────────────────────────────────────────

function SessionRow({
  session,
  active,
  indent = false,
  pinned = false,
  unread = false,
  onOpen,
  onTogglePin,
  onDelete,
}: {
  session: SessionInfo;
  active: boolean;
  indent?: boolean;
  pinned?: boolean;
  unread?: boolean;
  onOpen: () => void;
  onTogglePin: () => void;
  onDelete: () => void;
}) {
  const handleClick = (e: React.MouseEvent | React.KeyboardEvent) => {
    // Shift-click pins/unpins a chat (hinted in the PINNED empty state).
    if (e.shiftKey) {
      onTogglePin();
      return;
    }
    onOpen();
  };

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          handleClick(e);
        }
      }}
      className={cn(
        "group relative flex w-full min-w-0 cursor-pointer select-none items-center gap-2 rounded-sm py-1.5 pr-2 text-left transition",
        indent ? "pl-7" : "pl-2.5",
        active
          ? "bg-primary/12 text-foreground"
          : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground",
      )}
    >
      {pinned ? (
        <Pin className={cn("h-3 w-3 shrink-0", active ? "text-primary" : "text-muted-foreground/60")} />
      ) : (
        <MessageSquare className={cn("h-3.5 w-3.5 shrink-0", active ? "text-primary" : "text-muted-foreground/60")} />
      )}
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium leading-5">
        {threadTitle(session)}
      </span>
      {unread && (
        <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" title="New response" />
      )}
      <span className="shrink-0 text-[10px] text-muted-foreground/50 group-hover:hidden">
        {timeAgo(session.last_active)}
      </span>
      <button
        type="button"
        className="absolute right-1.5 hidden rounded p-0.5 text-muted-foreground/50 hover:text-destructive group-hover:block"
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        aria-label="Delete thread"
      >
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  );
}

// ── ProjectGroup ──────────────────────────────────────────────────────────────

function ProjectGroup({
  project,
  threads,
  isExpanded,
  selectedId,
  unreadSessionIds,
  pinnedIds,
  onToggle,
  onOpen,
  onTogglePin,
  onDelete,
  onNewThread,
  onDeleteProject,
}: {
  project: WorkspaceProject;
  threads: SessionInfo[];
  isExpanded: boolean;
  selectedId: string | null;
  unreadSessionIds: Set<string>;
  pinnedIds: Set<string>;
  onToggle: () => void;
  onOpen: (id: string) => void;
  onTogglePin: (id: string) => void;
  onDelete: (id: string) => void;
  onNewThread: (slug: string) => void;
  onDeleteProject: (slug: string) => void;
}) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  return (
    <div>
      <div className="group flex items-center gap-1.5 rounded-sm px-1.5 py-1 transition hover:bg-secondary/50">
        <button type="button" className="flex min-w-0 flex-1 items-center gap-1.5 text-left" onClick={onToggle}>
          <span className="text-muted-foreground/50">
            {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </span>
          <FolderOpen className="h-3.5 w-3.5 shrink-0 text-amber-300/70" />
          <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-foreground/80">
            {project.name}
          </span>
        </button>
        <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition group-hover:opacity-100">
          <button
            type="button"
            title="New thread in this project"
            className="rounded p-0.5 text-muted-foreground/60 hover:text-foreground"
            onClick={(e) => {
              e.stopPropagation();
              onNewThread(project.slug);
            }}
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="Delete project"
            className="rounded p-0.5 text-muted-foreground/60 hover:text-destructive"
            onClick={(e) => {
              e.stopPropagation();
              setShowDeleteConfirm(true);
            }}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
        {threads.length > 0 && (
          <Badge variant="secondary" className="h-4 shrink-0 px-1 text-[10px]">
            {threads.length}
          </Badge>
        )}
      </div>

      {showDeleteConfirm && (
        <div className="mx-1 mb-1 rounded-sm border border-destructive/40 bg-background p-2 text-xs">
          <p className="mb-1.5 text-foreground">
            Delete <span className="font-semibold">{project.name}</span>?
          </p>
          <p className="mb-2 text-muted-foreground">Removes all project files permanently.</p>
          <div className="flex gap-1">
            <Button
              size="sm"
              variant="destructive"
              className="h-6 flex-1 text-xs"
              onClick={() => {
                onDeleteProject(project.slug);
                setShowDeleteConfirm(false);
              }}
            >
              Delete
            </Button>
            <Button size="sm" variant="ghost" className="h-6 w-6 p-0" onClick={() => setShowDeleteConfirm(false)}>
              <X className="h-3 w-3" />
            </Button>
          </div>
        </div>
      )}

      {isExpanded && (
        <div className="pb-1">
          {threads.length === 0 ? (
            <p className="py-1 pl-9 text-[11px] italic text-muted-foreground/40">No chats</p>
          ) : (
            threads.map((t) => (
              <SessionRow
                key={t.id}
                session={t}
                active={selectedId === t.id}
                indent
                pinned={pinnedIds.has(t.id)}
                unread={unreadSessionIds.has(t.id)}
                onOpen={() => onOpen(t.id)}
                onTogglePin={() => onTogglePin(t.id)}
                onDelete={() => onDelete(t.id)}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── Collapsible section header ──────────────────────────────────────────────────

const SECTION_COLLAPSE_KEY = "spark.sidebar.collapsedSections";

function loadCollapsedSections(): Set<string> {
  try {
    const raw = localStorage.getItem(SECTION_COLLAPSE_KEY);
    return raw ? new Set(JSON.parse(raw) as string[]) : new Set();
  } catch {
    return new Set();
  }
}

function saveCollapsedSections(collapsed: Set<string>) {
  try {
    localStorage.setItem(SECTION_COLLAPSE_KEY, JSON.stringify([...collapsed]));
  } catch {
    // ignore (e.g. private browsing)
  }
}

function SectionHeader({
  label,
  collapsed,
  onToggle,
  actions,
}: {
  label: string;
  collapsed: boolean;
  onToggle: () => void;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between px-2 pb-1">
      <button
        type="button"
        onClick={onToggle}
        className="flex min-w-0 items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50 hover:text-foreground"
      >
        {collapsed ? <ChevronRight className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        <span>{label}</span>
      </button>
      {actions && <div className="flex items-center gap-0.5">{actions}</div>}
    </div>
  );
}

// ── SidebarSessions ───────────────────────────────────────────────────────────

export function SidebarSessions({
  onOpenSession,
  onNewProjectThread,
}: {
  /** Navigate to the chat page + select the session. */
  onOpenSession: (id: string) => void;
  /** Navigate to the chat page + open the project compose view. */
  onNewProjectThread: (slug: string) => void;
}) {
  const {
    projects,
    loadingProjects,
    loadingSessions,
    sessions,
    displayedSessions,
    searchQ,
    setSearchQ,
    searchResults,
    searching,
    pinnedIds,
    togglePin,
    selectedId,
    unreadSessionIds,
    expandedProjects,
    toggleProjectExpanded,
    deleteSession,
    deleteProject,
    createProject,
  } = useSessionStore();

  const searchInputRef = useRef<HTMLInputElement>(null);
  const [creatingProject, setCreatingProject] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");
  const [savingProject, setSavingProject] = useState(false);
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(loadCollapsedSections);

  const toggleSection = (section: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      saveCollapsedSections(next);
      return next;
    });
  };

  // Cmd+F focuses the session search; Cmd+K stays reserved for the palette.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "f") {
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const pinnedSessions = useMemo(
    () => displayedSessions.filter((s) => pinnedIds.has(s.id)),
    [displayedSessions, pinnedIds],
  );

  const ungrouped = useMemo(
    () => displayedSessions.filter((s) => !slugFromSource(s.source)),
    [displayedSessions],
  );

  const bySlug = useMemo(() => {
    const map = new Map<string, SessionInfo[]>();
    for (const s of displayedSessions) {
      const slug = slugFromSource(s.source);
      if (!slug) continue;
      const list = map.get(slug) ?? [];
      list.push(s);
      map.set(slug, list);
    }
    return map;
  }, [displayedSessions]);

  const handleCreateProject = async () => {
    const name = newProjectName.trim();
    if (!name || savingProject) return;
    setSavingProject(true);
    try {
      await createProject(name);
      setNewProjectName("");
      setCreatingProject(false);
    } catch (e) {
      console.error("Create project failed", e);
    } finally {
      setSavingProject(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Search */}
      <div className="shrink-0 px-2 pb-1 pt-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/60" />
          <Input
            ref={searchInputRef}
            className="h-7 pl-7 pr-8 text-[12px]"
            placeholder="Search sessions…"
            value={searchQ}
            onChange={(e) => setSearchQ(e.target.value)}
          />
          {searching && (
            <Loader2 className="absolute right-2 top-1/2 h-3 w-3 -translate-y-1/2 animate-spin text-muted-foreground/60" />
          )}
          {searchQ && !searching && (
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground/60 hover:text-foreground"
              onClick={() => setSearchQ("")}
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Scrollable list */}
      <div className="scrollbar-always min-h-0 flex-1 overflow-y-auto px-1 pb-2">
        {/* PINNED */}
        <div className="pt-2">
          <div className="flex items-center gap-1.5 px-2 pb-1">
            <Pin className="h-3 w-3 text-muted-foreground/50" />
            <span className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50">
              Pinned
            </span>
          </div>
          {pinnedSessions.length === 0 ? (
            <p className="px-2.5 pb-1 text-[11px] italic text-muted-foreground/40">
              Shift-click a chat to pin
            </p>
          ) : (
            pinnedSessions.map((s) => (
              <SessionRow
                key={`pin-${s.id}`}
                session={s}
                active={selectedId === s.id}
                pinned
                unread={unreadSessionIds.has(s.id)}
                onOpen={() => onOpenSession(s.id)}
                onTogglePin={() => togglePin(s.id)}
                onDelete={() => void deleteSession(s.id)}
              />
            ))
          )}
        </div>

        {/* SESSIONS */}
        <div className="pt-3">
          <SectionHeader
            label="Sessions"
            collapsed={collapsedSections.has("sessions")}
            onToggle={() => toggleSection("sessions")}
            actions={
              <>
                {(loadingSessions || loadingProjects) && !sessions.length && (
                  <Loader2 className="h-3 w-3 animate-spin text-muted-foreground/40" />
                )}
                <button
                  type="button"
                  title="New project workspace"
                  className="rounded p-0.5 text-muted-foreground/50 transition hover:bg-secondary hover:text-foreground"
                  onClick={() => setCreatingProject(true)}
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </>
            }
          />

          {!collapsedSections.has("sessions") && creatingProject && (
            <div className="mx-1.5 mb-2 flex flex-col gap-1.5 rounded-sm border border-border bg-background/60 p-2">
              <Input
                autoFocus
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                placeholder="Project name"
                className="h-7 text-xs"
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleCreateProject();
                  if (e.key === "Escape") {
                    setCreatingProject(false);
                    setNewProjectName("");
                  }
                }}
              />
              <div className="flex gap-1">
                <Button
                  size="sm"
                  className="h-6 flex-1 text-xs"
                  onClick={() => void handleCreateProject()}
                  disabled={savingProject}
                >
                  {savingProject ? <Loader2 className="h-3 w-3 animate-spin" /> : "Create"}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-6 w-6 p-0"
                  onClick={() => {
                    setCreatingProject(false);
                    setNewProjectName("");
                  }}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            </div>
          )}

          {!collapsedSections.has("sessions") && (
            <>
              {/* Project workspace groups */}
              {projects.map((project) => (
                <ProjectGroup
                  key={project.slug}
                  project={project}
                  threads={bySlug.get(project.slug) ?? []}
                  isExpanded={expandedProjects.has(project.slug) || Boolean(searchResults)}
                  selectedId={selectedId}
                  unreadSessionIds={unreadSessionIds}
                  pinnedIds={pinnedIds}
                  onToggle={() => toggleProjectExpanded(project.slug)}
                  onOpen={onOpenSession}
                  onTogglePin={togglePin}
                  onDelete={(id) => void deleteSession(id)}
                  onNewThread={onNewProjectThread}
                  onDeleteProject={(slug) => void deleteProject(slug)}
                />
              ))}

              {searchResults !== null && displayedSessions.length === 0 && (
                <p className="px-2.5 py-2 text-[11px] text-muted-foreground/50">
                  No results for "{searchQ}"
                </p>
              )}
              {searchResults === null && !loadingSessions && ungrouped.length === 0 && projects.length === 0 && (
                <p className="px-2.5 py-2 text-[11px] text-muted-foreground/40">No sessions yet</p>
              )}
            </>
          )}
        </div>

        {/* CHATS (ungrouped sessions) */}
        {ungrouped.length > 0 && (
          <div className="pt-3">
            <SectionHeader
              label="Chats"
              collapsed={collapsedSections.has("chats")}
              onToggle={() => toggleSection("chats")}
            />
            {!collapsedSections.has("chats") &&
              ungrouped.map((s) => (
                <SessionRow
                  key={s.id}
                  session={s}
                  active={selectedId === s.id}
                  pinned={pinnedIds.has(s.id)}
                  unread={unreadSessionIds.has(s.id)}
                  onOpen={() => onOpenSession(s.id)}
                  onTogglePin={() => togglePin(s.id)}
                  onDelete={() => void deleteSession(s.id)}
                />
              ))}
          </div>
        )}
      </div>
    </div>
  );
}
