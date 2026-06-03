import type { WorkflowNodeType, WorkflowNodeResult } from "@/lib/api";

/** dataTransfer MIME used when dragging a node type from the browser onto the canvas. */
export const CANVAS_DND_MIME = "application/spark-canvas-node";

/** What lives in a React Flow node's `data` for a Canvas node. */
export interface CanvasNodeData {
  nodeType: string; // engine type, e.g. "tool" | "agent" | "trigger.manual" | "display.iframe"
  label: string;
  emoji?: string;
  category: WorkflowNodeType["category"];
  tool?: string;
  schema?: WorkflowNodeType["schema"];
  description?: string;
  params: Record<string, unknown>;
  result?: WorkflowNodeResult | null;
  [key: string]: unknown;
}

/** Map an engine node type to the React Flow render component key. */
export function renderTypeFor(nodeType: string): string {
  switch (nodeType) {
    case "display.iframe":
      return "iframe";
    case "display.preview":
      return "preview";
    case "display.media":
      return "media";
    case "display.note":
      return "note";
    case "display.render":
      return "render";
    default:
      return "workflow";
  }
}

export const CATEGORY_ACCENT: Record<string, string> = {
  trigger: "text-emerald-400",
  action: "text-sky-400",
  control: "text-amber-400",
  agent: "text-violet-400",
  io: "text-rose-400",
  display: "text-muted-foreground",
};

/** Sensible default params when a node type is dropped. */
export function defaultParams(t: WorkflowNodeType): Record<string, unknown> {
  if (t.type === "display.iframe") return { url: "https://example.com", allowDomains: "", blockDomains: "" };
  if (t.type === "display.preview") return { url: "https://example.com" };
  if (t.type === "display.media") return { url: "" };
  if (t.type === "display.note") return { text: "" };
  if (t.type === "display.render") return { format: "text", content: "" };
  if (t.type === "agent") return { prompt: "", model: "", maxIterations: 10, toolsets: "", skipMemory: false };
  if (t.type === "workflow.subworkflow") return { scope: "global", slug: "", canvasId: "" };
  if (t.type === "memory.context") return { mode: "write", key: "default", value: "" };
  if (t.type === "trigger.manual") return { payload: "" };
  if (t.type === "data.set") return { fields: "{}" };
  if (t.type === "control.if") return { field: "value", equals: "" };
  if (t.type === "control.switch") return { field: "value", case: "", cases: "[]" };
  if (t.type === "control.loop") return { count: 1, batchSize: 1 };
  if (t.type === "action.code") return { code: "output = items" };
  if (t.type === "action.http") return { method: "GET", url: "", headers: "{}", body: "", timeout: 20 };
  if (t.type === "action.wait") return { seconds: 1 };
  if (t.type === "io.file_source") return { source: "files", slug: "", path: "", mode: "text" };
  if (t.type === "io.write_file") return { source: "files", slug: "", path: "", content: "" };
  if (t.type === "io.read_table") return { source: "files", slug: "", path: "" };
  if (t.type === "io.write_table") return { source: "files", slug: "", path: "", rows: "" };
  if (t.type === "tool") return { tool: t.tool, args: "{}" };
  // Seed from JSON-schema defaults where available.
  const out: Record<string, unknown> = {};
  const props = t.schema?.properties ?? {};
  for (const [k, p] of Object.entries(props)) {
    if (p.default !== undefined) out[k] = p.default;
  }
  return out;
}
