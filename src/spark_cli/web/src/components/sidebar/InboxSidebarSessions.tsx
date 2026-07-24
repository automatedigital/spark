import { useEffect, useMemo, useRef, useState } from "react";
import {
  Check,
  CircleCheck,
  CircleDashed,
  Folder,
  MessageSquare,
  Search,
  Undo2,
  X,
} from "lucide-react";
import type { SessionInfo } from "@/lib/api";
import { threadTitle } from "@/components/chat/ThreadRow";
import { useSessionStore, slugFromSource } from "@/lib/sessionStore";
import { cn, timeAgo } from "@/lib/utils";

const SETTLED_KEY = "spark.sidebar-beta.settled";

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
}: {
  session: SessionInfo;
  active: boolean;
  unread: boolean;
  project: string;
  onOpen: () => void;
  onSettle: () => void;
}) {
  const working = session.is_active && session.ended_at === null;
  return (
    <li className="list-none py-0.5">
      <div
        role="button"
        tabIndex={0}
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
}: {
  session: SessionInfo;
  active: boolean;
  settled: boolean;
  onOpen: () => void;
  onToggleSettled: () => void;
}) {
  return (
    <li className="list-none">
      <div
        role="button"
        tabIndex={0}
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

export function InboxSidebarSessions({
  onOpenSession,
  onNewProjectThread,
}: {
  onOpenSession: (id: string) => void;
  onNewProjectThread: (slug: string) => void;
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
  } = useSessionStore();
  const searchRef = useRef<HTMLInputElement>(null);
  const [settled, setSettled] = useState<SettledRecord>(readSettled);
  const [showSettled, setShowSettled] = useState(10);

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
  const active = visible.filter((session) => !settled[session.id]);
  const settledSessions = visible.filter((session) => Boolean(settled[session.id]));

  const toggleSettled = (session: SessionInfo) => {
    setSettled((current) => {
      const next = { ...current };
      if (next[session.id]) delete next[session.id];
      else next[session.id] = Date.now() / 1000;
      writeSettled(next);
      return next;
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
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

      {projects.length > 0 && (
        <div className="flex shrink-0 items-center px-2 py-2">
          <div className="scrollbar-none flex min-w-0 flex-1 gap-1 overflow-x-auto">
            <button
              type="button"
              onClick={() => setProjectScope(null)}
              className={cn("shrink-0 rounded-full border px-2.5 py-1 text-[11px] transition", projectScope === null ? "border-foreground/20 bg-foreground/10 text-foreground" : "border-border text-muted-foreground hover:text-foreground")}
            >
              All
            </button>
            {projects.map((project) => (
              <button
                key={project.slug}
                type="button"
                onClick={() => setProjectScope(project.slug)}
                onDoubleClick={() => onNewProjectThread(project.slug)}
                title="Double-click to start a thread"
                className={cn("shrink-0 rounded-full border px-2.5 py-1 text-[11px] transition", projectScope === project.slug ? "border-foreground/20 bg-foreground/10 text-foreground" : "border-border text-muted-foreground hover:text-foreground")}
              >
                {project.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="scrollbar-always min-h-0 flex-1 overflow-y-auto px-1.5 pb-3" data-testid="session-sidebar-scroll">
        {active.length > 0 && (
          <section>
            <div className="flex items-center justify-between px-1.5 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/45">
              <span>Inbox</span><span>{active.length}</span>
            </div>
            <ul>
              {active.map((session) => (
                <InboxCard key={session.id} session={session} active={selectedId === session.id} unread={unreadSessionIds.has(session.id)} project={projectName(session.source, projectNames)} onOpen={() => onOpenSession(session.id)} onSettle={() => toggleSettled(session)} />
              ))}
            </ul>
          </section>
        )}

        {settledSessions.length > 0 && (
          <section className="mt-2 border-t border-border/50 pt-2">
            <div className="flex items-center justify-between px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground/30">
              <span>Done</span><span>{settledSessions.length}</span>
            </div>
            <ul>{settledSessions.slice(0, showSettled).map((session) => <SlimRow key={session.id} session={session} active={selectedId === session.id} settled onOpen={() => onOpenSession(session.id)} onToggleSettled={() => toggleSettled(session)} />)}</ul>
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
