import type { Edge, Node, Viewport } from "@xyflow/react";
import type { CanvasDoc, CanvasScope, WorkflowNodeType } from "@/lib/api";
import { defaultParams, renderTypeFor, type CanvasNodeData } from "./types";

interface OpenCanvas {
  id: string;
  name: string;
  scope: CanvasScope;
  slug: string | null;
}

let nodeSeq = 1;

export const newNodeId = () => `n${Date.now().toString(36)}_${nodeSeq++}`;

export function sanitizeCanvasId(value: string): string {
  return value.trim().replace(/[^a-zA-Z0-9_\- ]/g, "").slice(0, 80) || "Untitled";
}

export function canvasIdentityKey(scope: CanvasScope, slug: string | null | undefined, id: string): string {
  return `${scope}:${slug ?? ""}:${id}`;
}

export function makeCanvasNode(
  t: WorkflowNodeType,
  position: { x: number; y: number },
  params?: Record<string, unknown>,
): Node {
  const data: CanvasNodeData = {
    nodeType: t.type,
    label: t.label,
    emoji: t.emoji,
    category: t.category,
    tool: t.tool,
    schema: t.schema,
    description: t.description,
    params: { ...defaultParams(t), ...(params ?? {}) },
    result: null,
  };
  return { id: newNodeId(), type: renderTypeFor(t.type), position, data };
}

export function toCanvasDoc(
  base: OpenCanvas | null,
  name: string,
  scope: CanvasScope,
  slug: string | null,
  nodes: Node[],
  edges: Edge[],
  viewport: Viewport,
  expectedRevision?: string | null,
): CanvasDoc {
  const id = sanitizeCanvasId(base?.id ?? name);
  return {
    id,
    name: name.trim() || id,
    scope,
    slug: scope === "project" ? slug : null,
    nodes: nodes.map((n) => {
      const d = n.data as CanvasNodeData;
      return {
        id: n.id,
        type: d.nodeType,
        position: n.position,
        params: d.params ?? {},
        data: { label: d.label, emoji: d.emoji, category: d.category, tool: d.tool },
        width: n.width,
        height: n.height,
      };
    }) as CanvasDoc["nodes"],
    edges: edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      sourceHandle: e.sourceHandle ?? null,
      targetHandle: e.targetHandle ?? null,
    })) as CanvasDoc["edges"],
    viewport,
    version: 2,
    expectedRevision: expectedRevision ?? null,
  };
}

export function fromCanvasDoc(doc: CanvasDoc): { nodes: Node[]; edges: Edge[]; viewport: Viewport } {
  const nodes: Node[] = (doc.nodes ?? []).map((n) => {
    const stored = n as unknown as {
      id: string;
      type: string;
      position: { x: number; y: number };
      params?: Record<string, unknown>;
      data?: Record<string, unknown>;
      width?: number | null;
      height?: number | null;
    };
    const d = (stored.data ?? {}) as Record<string, unknown>;
    const data: CanvasNodeData = {
      nodeType: stored.type,
      label: String(d.label ?? stored.type),
      emoji: d.emoji as string | undefined,
      category: (d.category as CanvasNodeData["category"]) ?? "action",
      tool: d.tool as string | undefined,
      params: stored.params ?? {},
      result: null,
    };
    return {
      id: stored.id,
      type: renderTypeFor(stored.type),
      position: stored.position ?? { x: 0, y: 0 },
      data,
      width: typeof stored.width === "number" ? stored.width : typeof d.width === "number" ? d.width : undefined,
      height: typeof stored.height === "number" ? stored.height : typeof d.height === "number" ? d.height : undefined,
    };
  });
  return {
    nodes,
    edges: (doc.edges as unknown as Edge[]) ?? [],
    viewport: doc.viewport ?? { x: 0, y: 0, zoom: 1 },
  };
}
