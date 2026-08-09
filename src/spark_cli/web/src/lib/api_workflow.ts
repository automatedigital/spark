/** workflow endpoints, split out of api.ts. */

import {
  fetchJSON,
  sseUrl,
} from "./apiHelpers";
import type {
  CanvasDoc,
  WorkflowExecutionDetail,
  WorkflowExecutionSummary,
  WorkflowItem,
  WorkflowNodeType,
  WorkflowRunResult,
  WorkflowTrigger,
} from "./apiTypes";

export const workflowApi = {
  getWorkflowNodeTypes: () =>
    fetchJSON<{ nodeTypes: WorkflowNodeType[] }>("/api/workflows/node-types"),
  runWorkflow: (doc: CanvasDoc, trigger = "manual") =>
    fetchJSON<WorkflowRunResult>("/api/workflows/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc, trigger }),
    }),
  runWorkflowAsync: (doc: CanvasDoc, trigger = "manual") =>
    fetchJSON<{ executionId: string; status: string }>("/api/workflows/run-async", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc, trigger }),
    }),
  streamWorkflowRun: (executionId: string): EventSource =>
    new EventSource(sseUrl(`/api/workflows/runs/${encodeURIComponent(executionId)}/events`)),
  cancelWorkflowRun: (executionId: string) =>
    fetchJSON<{ ok: boolean; executionId: string; status: string }>(
      `/api/workflows/runs/${encodeURIComponent(executionId)}/cancel`,
      { method: "POST" },
    ),
  runWorkflowNode: (doc: CanvasDoc, nodeId: string, seed?: WorkflowItem[]) =>
    fetchJSON<WorkflowRunResult>("/api/workflows/run-node", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc, nodeId, seed }),
    }),
  listWorkflowExecutions: (canvas?: string, scope?: string, slug?: string | null) => {
    const qs = new URLSearchParams();
    if (canvas) qs.set("canvas", canvas);
    if (scope) qs.set("scope", scope);
    if (slug) qs.set("slug", slug);
    return fetchJSON<{ executions: WorkflowExecutionSummary[] }>(
      `/api/workflows/executions${qs.toString() ? `?${qs}` : ""}`,
    );
  },
  getWorkflowExecution: (executionId: string) =>
    fetchJSON<WorkflowExecutionDetail>(`/api/workflows/executions/${encodeURIComponent(executionId)}`),
  registerWorkflowTriggers: (doc: CanvasDoc) =>
    fetchJSON<{ ok: boolean; triggers: WorkflowTrigger[] }>("/api/workflows/triggers/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doc }),
    }),

  // ── Canvas ──
};
