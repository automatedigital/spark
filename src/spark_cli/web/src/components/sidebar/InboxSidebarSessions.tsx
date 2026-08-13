import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import {
  ChevronDown,
  Check,
  CircleCheck,
  CircleDashed,
  Folder,
  FolderOpen,
  FolderPlus,
  MessageSquare,
  Pencil,
  Search,
  Undo2,
  X,
} from "lucide-react";
import type { SessionInfo } from "@/lib/api";
import { threadTitle } from "@/components/chat/ThreadRow";
import { sortSessionsNewestFirst } from "@/components/sidebar/sidebarRows";
import { useSessionStore, slugFromSource } from "@/lib/sessionStore";
import { cn, timeAgo } from "@/lib/utils";
import { ProjectSourceDialog } from "@/components/sidebar/ProjectSourceDialog";
import { ProjectWizard } from "@/components/sidebar/SidebarSessions";

const SETTLED_KEY = "spark.sidebar-beta.settled";
const SESSION_DRAG_MIME = "application/x-spark-session-id";

type SettledRecord = Record<string, number>;

function readSettled(): SettledRecord {
  try {
    return JSON.parse(localStorage.getItem(SETTLED_KEY) ?? "{}") as SettledRecord;
  } catch {
    return {};
  }
}

function writeSettled(value: SettledRecord) {
  try {
    localStorage.setItem(SETTLED_KEY, JSON.stringify(value));
  } catch {
    // Local preference only; a storage failure should never block navigation.
  }
}

function compactTime(timestamp: number) {
  return timeAgo(timestamp).replace(/ ago$/, "").replace(/^just now$/, "now");
}

function projectName(source: string | null, names: ReadonlyMap<string, string>) {
  const slug = slugFromSource(source);
  if (!slug) return "Spark";
  return names.get(slug) ?? slug.replace(/[-_]/g, " ");
}

function InboxCard({
  session,
  active,
  unread,
  project,
  onOpen,
  onSettle,
  dragging,
  onDragStart,
  onDragEnd,
}: {
  session: SessionInfo;
  active: boolean;
  unread: boolean;
  project: string;
  onOpen: () => void;
  onSettle: () => void;
  dragging: boolean;
  onDragStart: (event: DragEvent<HTMLDivElement>) => void;
  onDragEnd: () => void;
}) {
  const working = session.is_active && session.ended_at === null;
  return (
    <li className="list-none py-0.5">
      <div
        role="button"
        tabIndex={0}
        draggable
        aria-grabbed={dragging}
        title="Drag to move thread"
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onClick={onOpen}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onOpen();
          }
        }}
        className={cn(
          "group/inbox relative w-full cursor-pointer select-none overflow-hidden rounded-lg text-left transition-colors",
          active
            ? "bg-foreground/[0.11] text-foreground"
            : "bg-foreground/[0.035] hover:bg-foreground/[0.07]",
          dragging && "opacity-45 ring-1 ring-foreground/20",
        )}
      >
        <div className="px-2.5 py-2">
          <div className="flex h-5 min-w-0 items-center gap-1.5">
            <span className="grid h-4 w-4 shrink-0 place-items-center rounded bg-foreground/[0.08]">
              <Folder className="h-2.5 w-2.5 text-muted-foreground" />
            </span>
            <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-muted-foreground/70">
              {project}
            </span>
            <span className="relative ml-auto flex h-5 min-w-12 items-center justify-end">
              <span
                className={cn(
                  "inline-flex items-center gap-1 text-[11px] transition-opacity group-hover/inbox:opacity-0",
                  working
                    ? "font-semibold text-blue-400"
                    : unread
                      ? "font-semibold text-emerald-400"
                      : "text-muted-foreground/55",
                )}
              >
                {working ? <CircleDashed className="h-3 w-3 animate-spin" /> : unread ? <CircleCheck className="h-3 w-3" /> : null}
                {working ? "Working" : unread ? "Done" : compactTime(session.last_active)}
              </span>
              <button
                type="button"
                aria-label="Mark thread as done"
                title="Done"
                onClick={(event) => {
                  event.stopPropagation();
                  onSettle();
                }}
                className="absolute right-0 inline-flex h-6 items-center gap-1 rounded-md border border-border bg-background px-2 text-[10px] text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover/inbox:opacity-100"
              >
                <Check className="h-3 w-3" /> Done
              </button>
            </span>
          </div>
          <div className={cn("mt-1 line-clamp-2 text-[13px] leading-5", unread || working ? "font-semibold" : "font-medium text-foreground/90")}>
            {threadTitle(session)}
          </div>
          <div className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[10px] text-muted-foreground/55">
            <span className="min-w-0 flex-1 truncate">{session.preview || `${session.message_count} messages`}</span>
            {session.model && <span className="shrink-0 font-mono">{session.model.split("/").pop()}</span>}
          </div>
        </div>
      </div>
    </li>
  );
}

function SlimRow({
  session,
  active,
  settled,
  onOpen,
  onToggleSettled,
  dragging,
  onDragStart,
  onDragEnd,
}: {
  session: SessionInfo;
  active: boolean;
  settled: boolean;
  onOpen: () => void;
  onToggleSettled: () => void;
  dragging: boolean;
  onDragStart: (event: DragEvent<HTMLDivElement>) => void;
  onDragEnd: () => void;
}) {
  return (
    <li className="list-none">
      <div
        role="button"
        tabIndex={0}
        draggable
        aria-grabbed={dragging}
        title="Drag to move thread"
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        onClick={onOpen}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onOpen();
          }
        }}
        className={cn(
          "group/slim flex h-[34px] cursor-pointer items-center gap-2.5 rounded-md px-2.5 transition-colors hover:bg-foreground/[0.06]",
          active && "bg-foreground/[0.1] text-foreground",
          dragging && "opacity-45 ring-1 ring-foreground/20",
        )}
      >
        <MessageSquare className={cn("h-3.5 w-3.5 shrink-0", settled ? "text-muted-foreground/30" : "text-muted-foreground/50")} />
        <span className={cn("min-w-0 flex-1 truncate text-[13px]", settled ? "text-muted-foreground/45" : "text-muted-foreground/70", active && "text-foreground")}>
          {threadTitle(session)}
        </span>
        <span className="relative flex h-6 min-w-8 shrink-0 items-center justify-end">
          <span className="text-[12px] tabular-nums text-muted-foreground/35 transition-opacity group-hover/slim:opacity-0">
            {compactTime(session.last_active)}
          </span>
          <button
            type="button"
            aria-label={settled ? "Restore thread" : "Mark thread as done"}
            title={settled ? "Restore thread" : "Done"}
            onClick={(event) => {
              event.stopPropagation();
              onToggleSettled();
            }}
            className="absolute right-0 grid h-6 min-w-7 place-items-center rounded-md border border-border bg-background px-1.5 text-muted-foreground opacity-0 transition-opacity hover:text-foreground focus-visible:opacity-100 group-hover/slim:opacity-100"
          >
            {settled ? <Undo2 className="h-3 w-3" /> : <Check className="h-3 w-3" />}
          </button>
        </span>
      </div>
    </li>
  );
}

function ProjectScopeMenu({
  projects,
  value,
  draggingSessionId,
  dropTarget,
  onChange,
  onNewProject,
  onNewChat,
  onDragOver,
  onDragLeave,
  onDrop,
}: {
  projects: Array<{ slug: string; name: string }>;
  value: string | null;
  draggingSessionId: string | null;
  dropTarget: string | null;
  onChange: (slug: string | null) => void;
  onNewProject: () => void;
  onNewChat?: () => void;
  onDragOver: (target: string, event: DragEvent<HTMLButtonElement>) => void;
  onDragLeave: (target: string) => void;
  onDrop: (slug: string | null, event: DragEvent<HTMLButtonElement>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const selected = projects.find((project) => project.slug === value);
  const filtered = projects.filter((project) => !query.trim() || project.name.toLowerCase().includes(query.trim().toLowerCase()));

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const select = (slug: string | null) => {
    onChange(slug);
    setOpen(false);
  };

  return (
    <div ref={ref} className="relative min-w-0 flex-1">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={selected ? `Project: ${selected.name}` : "Project: all projects"}
        onClick={() => setOpen((current) => !current)}
        className="flex h-8 w-full items-center gap-2 rounded-md px-1.5 text-left text-[12px] text-muted-foreground transition hover:bg-foreground/[0.06] hover:text-foreground"
      >
        <FolderOpen className="h-3.5 w-3.5 shrink-0 text-muted-foreground/70" />
        <span className="min-w-0 flex-1 truncate">{selected?.name ?? "All projects"}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="absolute left-0 top-[calc(100%+6px)] z-[160] w-[min(270px,calc(100vw-1rem))] overflow-hidden rounded-lg border border-border bg-popover/95 p-1 shadow-2xl shadow-black/35 backdrop-blur-xl" role="menu">
          {projects.length > 6 && (
            <div className="flex items-center gap-2 border-b border-border/60 px-2 py-1.5">
              <Search className="h-3.5 w-3.5 text-muted-foreground/50" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search projects…"
                className="min-w-0 flex-1 bg-transparent text-xs outline-none placeholder:text-muted-foreground/40"
                aria-label="Search projects"
              />
            </div>
          )}
          <div className="max-h-64 overflow-y-auto py-1">
            <button
              type="button"
              role="menuitemradio"
              aria-checked={value === null}
              onClick={() => select(null)}
              onDragOver={(event) => onDragOver("__all__", event)}
              onDragLeave={() => onDragLeave("__all__")}
              onDrop={(event) => onDrop(null, event)}
              className={cn("flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[12px] transition", value === null ? "bg-foreground/10 text-foreground" : "text-muted-foreground hover:bg-foreground/[0.07] hover:text-foreground", dropTarget === "__all__" && "ring-1 ring-emerald-400/40")}
            >
              <Folder className="h-3.5 w-3.5 shrink-0 opacity-60" />
              <span className="truncate">All projects</span>
            </button>
            {filtered.map((project) => (
              <button
                key={project.slug}
                type="button"
                role="menuitemradio"
                aria-checked={value === project.slug}
                onClick={() => select(project.slug)}
                onDragOver={(event) => onDragOver(project.slug, event)}
                onDragLeave={() => onDragLeave(project.slug)}
                onDrop={(event) => onDrop(project.slug, event)}
                className={cn("flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-[12px] transition", value === project.slug ? "bg-foreground/10 text-foreground" : "text-muted-foreground hover:bg-foreground/[0.07] hover:text-foreground", dropTarget === project.slug && "ring-1 ring-emerald-400/40")}
              >
                <Folder className="h-3.5 w-3.5 shrink-0 opacity-60" />
                <span className="min-w-0 flex-1 truncate">{project.name}</span>
              </button>
            ))}
            {!filtered.length && <p className="px-2 py-2 text-[11px] text-muted-foreground/45">No projects found</p>}
          </div>
          {draggingSessionId && (
            <button
              type="button"
              onDragOver={(event) => onDragOver("__unfiled__", event)}
              onDragLeave={() => onDragLeave("__unfiled__")}
              onDrop={(event) => onDrop(null, event)}
              className={cn("flex h-8 w-full items-center gap-2 rounded-md border-t border-border/60 px-2 text-left text-[11px] text-muted-foreground transition hover:text-foreground", dropTarget === "__unfiled__" && "text-emerald-300")}
            >
              <X className="h-3.5 w-3.5" /> No project
            </button>
          )}
          <button type="button" onClick={() => { onNewProject(); setOpen(false); }} className="mt-1 flex h-8 w-full items-center gap-2 border-t border-border/60 px-2 text-left text-[11px] font-medium text-muted-foreground transition hover:text-foreground">
            <FolderPlus className="h-3.5 w-3.5" /> New project
          </button>
          {onNewChat && (
            <button type="button" onClick={() => { onNewChat(); setOpen(false); }} className="flex h-8 w-full items-center gap-2 px-2 text-left text-[11px] font-medium text-muted-foreground transition hover:text-foreground">
              <Pencil className="h-3.5 w-3.5" /> New chat
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function InboxSidebarSessions({
  onOpenSession,
  onNewThread,
}: {
  onOpenSession: (id: string) => void;
  onNewThread?: () => void;
}) {
  const {
    projects,
    displayedSessions,
    searchQ,
    setSearchQ,
    searching,
    selectedId,
    unreadSessionIds,
    sidebarProjectScope: projectScope,
    setSidebarProjectScope: setProjectScope,
    moveSessionToProject,
    createProject,
  } = useSessionStore();
  const searchRef = useRef<HTMLInputElement>(null);
  const [settled, setSettled] = useState<SettledRecord>(readSettled);
  const [showSettled, setShowSettled] = useState(10);
  const [draggingSessionId, setDraggingSessionId] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [dragError, setDragError] = useState<string | null>(null);
  const [creatingProject, setCreatingProject] = useState(false);
  const [sourceDialogOpen, setSourceDialogOpen] = useState(false);

  const projectNames = useMemo(() => new Map(projects.map((project) => [project.slug, project.name])), [projects]);
  const visible = useMemo(
    () => displayedSessions.filter((session) => projectScope === null || slugFromSource(session.source) === projectScope),
    [displayedSessions, projectScope],
  );

  // Activity newer than the explicit settle action returns work to the inbox.
  useEffect(() => {
    setSettled((current) => {
      let changed = false;
      const next = { ...current };
      for (const session of displayedSessions) {
        if (next[session.id] && session.last_active > next[session.id]) {
          delete next[session.id];
          changed = true;
        }
      }
      if (changed) writeSettled(next);
      return changed ? next : current;
    });
  }, [displayedSessions]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "f") {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Inbox membership is a lifecycle choice, not a runtime status. Completed
  // and quiet threads remain full cards until the user explicitly settles them.
  const active = sortSessionsNewestFirst(
    visible.filter((session) => !settled[session.id]),
  );
  const settledSessions = sortSessionsNewestFirst(
    visible.filter((session) => Boolean(settled[session.id])),
  );

  const toggleSettled = (session: SessionInfo) => {
    setSettled((current) => {
      const next = { ...current };
      if (next[session.id]) delete next[session.id];
      else next[session.id] = Date.now() / 1000;
      writeSettled(next);
      return next;
    });
  };

  const startSessionDrag = (sessionId: string, event: DragEvent<HTMLDivElement>) => {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData(SESSION_DRAG_MIME, sessionId);
    event.dataTransfer.setData("text/plain", sessionId);
    setDraggingSessionId(sessionId);
    setDragError(null);
  };

  const endSessionDrag = () => {
    setDraggingSessionId(null);
    setDropTarget(null);
  };

  const allowProjectDrop = (target: string, event: DragEvent<HTMLButtonElement>) => {
    if (!draggingSessionId) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    setDropTarget(target);
  };

  const dropSession = async (slug: string | null, event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    const sessionId = event.dataTransfer.getData(SESSION_DRAG_MIME)
      || event.dataTransfer.getData("text/plain")
      || draggingSessionId;
    endSessionDrag();
    if (!sessionId) return;
    try {
      await moveSessionToProject(sessionId, slug);
    } catch (error) {
      setDragError(error instanceof Error ? error.message : "Could not move thread");
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ProjectWizard
        open={creatingProject}
        onClose={() => setCreatingProject(false)}
        onCreate={async (request) => {
          await createProject(request);
        }}
      />
      <ProjectSourceDialog
        open={sourceDialogOpen}
        onClose={() => setSourceDialogOpen(false)}
        onChooseNewFolder={() => {
          setSourceDialogOpen(false);
          setCreatingProject(true);
        }}
        onCreate={async (request) => {
          await createProject(request);
        }}
      />
      <div className="shrink-0 px-2 pb-1 pt-2">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/55" />
          <input
            ref={searchRef}
            className="h-8 w-full rounded-md border border-border/70 bg-background/55 pl-7 pr-8 text-[12px] outline-none placeholder:text-muted-foreground/45 focus:border-foreground/25"
            placeholder="Search"
            value={searchQ}
            onChange={(event) => setSearchQ(event.target.value)}
          />
          {searchQ && !searching && (
            <button type="button" onClick={() => setSearchQ("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1 border-b border-border/40 px-2 pb-2 pt-1">
        <ProjectScopeMenu
          projects={projects}
          value={projectScope}
          draggingSessionId={draggingSessionId}
          dropTarget={dropTarget}
          onChange={setProjectScope}
          onNewProject={() => {
            setSourceDialogOpen(true);
          }}
          onNewChat={onNewThread}
          onDragOver={allowProjectDrop}
          onDragLeave={(target) => setDropTarget((current) => current === target ? null : current)}
          onDrop={(slug, event) => void dropSession(slug, event)}
        />
        <button type="button" onClick={() => setSourceDialogOpen(true)} className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground/65 transition hover:bg-foreground/[0.06] hover:text-foreground" aria-label="New project" title="New project">
          <FolderPlus className="h-3.5 w-3.5" />
        </button>
      </div>

      {dragError && (
        <p role="alert" className="shrink-0 px-3 pb-1 text-[11px] text-destructive">
          {dragError}
        </p>
      )}

      <div className="scrollbar-always min-h-0 flex-1 overflow-y-auto px-1.5 pb-3" data-testid="session-sidebar-scroll">
        {active.length > 0 && (
          <section>
            <div className="flex items-center justify-between px-1.5 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/45">
              <span>Inbox</span><span>{active.length}</span>
            </div>
            <ul>
              {active.map((session) => (
                <InboxCard
                  key={session.id}
                  session={session}
                  active={selectedId === session.id}
                  unread={unreadSessionIds.has(session.id)}
                  project={projectName(session.source, projectNames)}
                  onOpen={() => onOpenSession(session.id)}
                  onSettle={() => toggleSettled(session)}
                  dragging={draggingSessionId === session.id}
                  onDragStart={(event) => startSessionDrag(session.id, event)}
                  onDragEnd={endSessionDrag}
                />
              ))}
            </ul>
          </section>
        )}

        {settledSessions.length > 0 && (
          <section className="mt-2 border-t border-border/50 pt-2">
            <div className="flex items-center justify-between px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/30">
              <span>Done</span><span>{settledSessions.length}</span>
            </div>
            <ul>
              {settledSessions.slice(0, showSettled).map((session) => (
                <SlimRow
                  key={session.id}
                  session={session}
                  active={selectedId === session.id}
                  settled
                  onOpen={() => onOpenSession(session.id)}
                  onToggleSettled={() => toggleSettled(session)}
                  dragging={draggingSessionId === session.id}
                  onDragStart={(event) => startSessionDrag(session.id, event)}
                  onDragEnd={endSessionDrag}
                />
              ))}
            </ul>
            {settledSessions.length > showSettled && <button type="button" onClick={() => setShowSettled((count) => count + 25)} className="w-full py-2 text-[11px] text-muted-foreground/45 hover:text-foreground">Show more</button>}
          </section>
        )}

        {!active.length && !settledSessions.length && (
          <div className="px-4 py-10 text-center">
            <CircleCheck className="mx-auto mb-3 h-5 w-5 text-muted-foreground/35" />
            <p className="text-[13px] font-medium text-foreground/75">Inbox clear</p>
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground/45">Start a thread when you’re ready to make something.</p>
          </div>
        )}
      </div>
    </div>
  );
}
