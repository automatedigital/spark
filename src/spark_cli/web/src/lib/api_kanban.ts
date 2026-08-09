/** kanban endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  KanbanBoardResponse,
  KanbanBulkPatchFields,
  KanbanBulkPatchResponse,
  KanbanDispatchResponse,
  KanbanTaskCreate,
  KanbanTaskDetail,
  KanbanTaskPatch,
  KanbanTaskRow,
} from "./apiTypes";

export const kanbanApi = {
  patchSessionKanban: (sessionId: string, status: string) =>
    fetchJSON<{ ok: boolean; session_id: string; status: string }>(
      `/api/sessions/${encodeURIComponent(sessionId)}/kanban`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      },
    ),

  // Web chat conversations
  getKanbanBoard: (params: {
    board?: string;
    tenant?: string | null;
    assignee?: string | null;
    archived?: boolean;
    q?: string | null;
  }) => {
    const qs = new URLSearchParams();
    if (params.board) qs.set("board", params.board);
    if (params.tenant) qs.set("tenant", params.tenant);
    if (params.assignee) qs.set("assignee", params.assignee);
    if (params.archived) qs.set("archived", "true");
    if (params.q) qs.set("q", params.q);
    const suffix = qs.toString() ? `?${qs}` : "";
    return fetchJSON<KanbanBoardResponse>(`/api/kanban/board${suffix}`);
  },
  getKanbanTask: (id: string) =>
    fetchJSON<KanbanTaskDetail>(`/api/kanban/tasks/${encodeURIComponent(id)}`),
  createKanbanTask: (body: KanbanTaskCreate) =>
    fetchJSON<KanbanTaskRow>("/api/kanban/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  patchKanbanTask: (id: string, body: KanbanTaskPatch) =>
    fetchJSON<KanbanTaskRow>(`/api/kanban/tasks/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  deleteKanbanTask: (id: string) =>
    fetchJSON<{ ok: boolean; deleted: string }>(`/api/kanban/tasks/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  bulkPatchKanbanTasks: (ids: string[], fields: KanbanBulkPatchFields) =>
    fetchJSON<KanbanBulkPatchResponse>("/api/kanban/tasks/bulk", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids, ...fields }),
    }),
  addKanbanComment: (taskId: string, body: string, author?: string) =>
    fetchJSON<{ ok: boolean; id?: string }>(
      `/api/kanban/tasks/${encodeURIComponent(taskId)}/comments`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ body, author: author ?? "web" }),
      },
    ),
  addKanbanLink: (parent_id: string, child_id: string) =>
    fetchJSON<{ ok: boolean }>("/api/kanban/links", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent_id, child_id }),
    }),
  deleteKanbanLink: (parent_id: string, child_id: string) =>
    fetchJSON<{ ok: boolean }>(
      `/api/kanban/links?${new URLSearchParams({ parent_id, child_id }).toString()}`,
      { method: "DELETE" },
    ),
  dispatchKanban: (max_tasks = 3, dry_run = false) =>
    fetchJSON<KanbanDispatchResponse>(
      `/api/kanban/dispatch?max_tasks=${max_tasks}&dry_run=${dry_run}`,
      { method: "POST" },
    ),
  completeKanbanTask: (id: string, summary: string, result = "") =>
    fetchJSON<KanbanTaskRow>(`/api/kanban/tasks/${encodeURIComponent(id)}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ summary, result, metadata: {} }),
    }),
  blockKanbanTask: (id: string, reason: string) =>
    fetchJSON<KanbanTaskRow>(`/api/kanban/tasks/${encodeURIComponent(id)}/block`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }),
  unblockKanbanTask: (id: string) =>
    fetchJSON<KanbanTaskRow>(`/api/kanban/tasks/${encodeURIComponent(id)}/unblock`, {
      method: "POST",
    }),

  // Admin surfaces
};
