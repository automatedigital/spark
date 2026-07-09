import type { SessionInfo, WorkspaceProject } from "@/lib/api";
import { slugFromSource } from "@/lib/sessionStore";

export type SidebarRow =
  | { key: "pinned:header"; kind: "pinned-header" }
  | { key: "pinned:empty"; kind: "pinned-empty" }
  | { key: "projects:header"; kind: "projects-header" }
  | { key: `project:${string}`; kind: "project"; project: WorkspaceProject; sessionCount: number }
  | { key: `project-empty:${string}`; kind: "project-empty"; projectSlug: string }
  | { key: "projects:empty"; kind: "projects-empty" }
  | { key: "search:empty"; kind: "search-empty"; query: string }
  | { key: "chats:header"; kind: "chats-header" }
  | { key: "chats:empty"; kind: "chats-empty" }
  | { key: "sessions:loading"; kind: "loading" }
  | { key: "sessions:more"; kind: "load-more" }
  | { key: "sessions:error"; kind: "load-error"; message: string }
  | {
      key: string;
      kind: "session";
      session: SessionInfo;
      placement: "pinned" | "project" | "chats";
      indent: boolean;
      pinned: boolean;
    };

export interface BuildSidebarRowsOptions {
  projects: WorkspaceProject[];
  sessions: SessionInfo[];
  pinnedIds: Set<string>;
  expandedProjects: Set<string>;
  collapsedSections: Set<string>;
  searchResultsActive: boolean;
  searchQ: string;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  loadError: string | null;
  dragging: boolean;
}

/**
 * Build the complete logical sidebar as one flat list. Keeping hierarchy out
 * of React makes expansion, paging, SSE reordering, and virtualization
 * deterministic and independently testable.
 */
export function buildSidebarRows(options: BuildSidebarRowsOptions): SidebarRow[] {
  const {
    projects,
    sessions,
    pinnedIds,
    expandedProjects,
    collapsedSections,
    searchResultsActive,
    searchQ,
    loading,
    loadingMore,
    hasMore,
    loadError,
    dragging,
  } = options;
  const rows: SidebarRow[] = [{ key: "pinned:header", kind: "pinned-header" }];
  const pinned = sessions.filter((session) => pinnedIds.has(session.id));
  if (pinned.length === 0) {
    rows.push({ key: "pinned:empty", kind: "pinned-empty" });
  } else {
    pinned.forEach((session) => rows.push({
      key: `pinned:${session.id}`,
      kind: "session",
      session,
      placement: "pinned",
      indent: false,
      pinned: true,
    }));
  }

  rows.push({ key: "projects:header", kind: "projects-header" });
  const bySlug = new Map<string, SessionInfo[]>();
  const ungrouped: SessionInfo[] = [];
  sessions.forEach((session) => {
    const slug = slugFromSource(session.source);
    if (!slug) {
      ungrouped.push(session);
      return;
    }
    const projectSessions = bySlug.get(slug) ?? [];
    projectSessions.push(session);
    bySlug.set(slug, projectSessions);
  });

  if (!collapsedSections.has("sessions")) {
    projects.forEach((project) => {
      const projectSessions = bySlug.get(project.slug) ?? [];
      rows.push({
        key: `project:${project.slug}` as const,
        kind: "project",
        project,
        sessionCount: projectSessions.length,
      });
      if (expandedProjects.has(project.slug) || searchResultsActive) {
        if (projectSessions.length === 0) {
          rows.push({
            key: `project-empty:${project.slug}` as const,
            kind: "project-empty",
            projectSlug: project.slug,
          });
        } else {
          projectSessions.forEach((session) => rows.push({
            key: `project-session:${project.slug}:${session.id}`,
            kind: "session",
            session,
            placement: "project",
            indent: true,
            pinned: pinnedIds.has(session.id),
          }));
        }
      }
    });

    if (searchResultsActive && sessions.length === 0) {
      rows.push({ key: "search:empty", kind: "search-empty", query: searchQ });
    } else if (!searchResultsActive && !loading && ungrouped.length === 0 && projects.length === 0) {
      rows.push({ key: "projects:empty", kind: "projects-empty" });
    }
  }

  if (ungrouped.length > 0 || dragging) {
    rows.push({ key: "chats:header", kind: "chats-header" });
    if (!collapsedSections.has("chats")) {
      if (ungrouped.length === 0) {
        rows.push({ key: "chats:empty", kind: "chats-empty" });
      } else {
        ungrouped.forEach((session) => rows.push({
          key: `chat:${session.id}`,
          kind: "session",
          session,
          placement: "chats",
          indent: false,
          pinned: pinnedIds.has(session.id),
        }));
      }
    }
  }

  if (!searchResultsActive) {
    if (loadError) rows.push({ key: "sessions:error", kind: "load-error", message: loadError });
    if (loadingMore) rows.push({ key: "sessions:loading", kind: "loading" });
    else if (hasMore) rows.push({ key: "sessions:more", kind: "load-more" });
  }
  return rows;
}

export function estimateSidebarRowHeight(row: SidebarRow): number {
  switch (row.kind) {
    case "pinned-header":
    case "projects-header":
    case "chats-header":
      return 32;
    case "project":
      return 30;
    case "session":
      return 32;
    default:
      return 30;
  }
}
