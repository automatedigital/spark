/** canvas endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  CanvasDoc,
  CanvasListResponse,
  CanvasScope,
} from "./apiTypes";

function canvasUrl(scope: CanvasScope, id: string, slug?: string | null): string {
  const encId = encodeURIComponent(id);
  if (scope === "project") {
    if (!slug) throw new Error("Project canvas requires a slug");
    return `/api/canvases/project/${encodeURIComponent(slug)}/${encId}`;
  }
  return `/api/canvases/global/${encId}`;
}

export const canvasApi = {
  canvasInteract: (body: { scope: string; slug: string | null; canvas_id: string; widget_id: string; value: string }) =>
    fetchJSON<{ ok: boolean }>(`/api/canvases/interact`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  // ── Memory ──
  listCanvases: () => fetchJSON<CanvasListResponse>("/api/canvases"),

  // Stateless, canvas-local agent turn (does NOT create a Chat-tab session).
  postCanvasChat: (
    message: string,
    history: Array<{ role: string; content: string }> = [],
    opts: { model?: string; slug?: string | null } = {},
  ) =>
    fetchJSON<{ ok: boolean; reply: string; model: string }>("/api/canvas/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history, model: opts.model, slug: opts.slug ?? null }),
    }),
  getCanvas: (scope: CanvasScope, id: string, slug?: string | null) =>
    fetchJSON<CanvasDoc>(canvasUrl(scope, id, slug)),
  saveCanvas: (doc: CanvasDoc) =>
    fetchJSON<{ ok: boolean; id: string; scope: CanvasScope; slug: string | null; updatedAt: string; revision: string }>(
      canvasUrl(doc.scope, doc.id, doc.slug),
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(doc),
      },
    ),
  deleteCanvas: (scope: CanvasScope, id: string, slug?: string | null) =>
    fetchJSON<{ ok: boolean; deleted: string }>(canvasUrl(scope, id, slug), {
      method: "DELETE",
    }),
};
