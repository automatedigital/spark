import { describe, expect, it } from "vitest";
import type { SessionInfo, WorkspaceProject } from "@/lib/api";
import { buildSidebarRows } from "./sidebarRows";

function session(id: string, source: string | null = "web"): SessionInfo {
  return {
    id,
    source,
    model: null,
    title: id,
    started_at: 1,
    ended_at: null,
    last_active: 1,
    is_active: false,
    message_count: 1,
    tool_call_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    preview: null,
    kanban_status: null,
    estimated_cost_usd: null,
  };
}

const projects: WorkspaceProject[] = [{
  slug: "alpha",
  name: "Alpha",
  path: "/tmp/alpha",
  mtime: 1,
  file_count: 0,
}];

describe("buildSidebarRows", () => {
  it("flattens pinned, project, and ungrouped sessions with stable unique keys", () => {
    const rows = buildSidebarRows({
      projects,
      sessions: [session("project-chat", "workspace:alpha"), session("loose-chat")],
      pinnedIds: new Set(["project-chat"]),
      expandedProjects: new Set(["alpha"]),
      collapsedSections: new Set(),
      searchResultsActive: false,
      searchQ: "",
      loading: false,
      loadingMore: false,
      hasMore: true,
      loadError: null,
      dragging: false,
    });

    expect(rows.map((row) => row.key)).toEqual([
      "pinned:header",
      "pinned:project-chat",
      "projects:header",
      "project:alpha",
      "project-session:alpha:project-chat",
      "chats:header",
      "chat:loose-chat",
      "sessions:more",
    ]);
    expect(new Set(rows.map((row) => row.key).values()).size).toBe(rows.length);
  });

  it("expands projects for search and reports an empty search result", () => {
    const rows = buildSidebarRows({
      projects,
      sessions: [],
      pinnedIds: new Set(),
      expandedProjects: new Set(),
      collapsedSections: new Set(),
      searchResultsActive: true,
      searchQ: "old thread",
      loading: false,
      loadingMore: false,
      hasMore: true,
      loadError: null,
      dragging: false,
    });

    expect(rows.some((row) => row.key === "project-empty:alpha")).toBe(true);
    expect(rows.some((row) => row.kind === "search-empty")).toBe(true);
    expect(rows.some((row) => row.kind === "load-more")).toBe(false);
  });

  it("does not materialize collapsed project children", () => {
    const rows = buildSidebarRows({
      projects,
      sessions: Array.from({ length: 500 }, (_, index) => session(`s${index}`, "workspace:alpha")),
      pinnedIds: new Set(),
      expandedProjects: new Set(),
      collapsedSections: new Set(),
      searchResultsActive: false,
      searchQ: "",
      loading: false,
      loadingMore: false,
      hasMore: false,
      loadError: null,
      dragging: false,
    });

    expect(rows.filter((row) => row.kind === "session")).toHaveLength(0);
    expect(rows.map((row) => row.key)).toEqual([
      "pinned:header",
      "pinned:empty",
      "projects:header",
      "project:alpha",
    ]);
  });
});
