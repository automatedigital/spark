/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, memo } from "react";
import { Handle, Position, NodeResizer, type NodeProps } from "@xyflow/react";
import { Loader2, Play, RefreshCw, ExternalLink, Settings2, CheckCircle2, XCircle } from "lucide-react";
import { CATEGORY_ACCENT, type CanvasNodeData } from "./types";

export interface CanvasNodeApi {
  updateNodeData: (id: string, patch: Partial<CanvasNodeData>) => void;
  updateParams: (id: string, patch: Record<string, unknown>) => void;
  runNode: (id: string) => void;
  openInspector: (id: string) => void;
  runningIds: Set<string>;
}

const noop = () => {};
export const CanvasNodeContext = createContext<CanvasNodeApi>({
  updateNodeData: noop,
  updateParams: noop,
  runNode: noop,
  openInspector: noop,
  runningIds: new Set(),
});

function useApi(id: string) {
  const api = useContext(CanvasNodeContext);
  return {
    setParams: (patch: Record<string, unknown>) => api.updateParams(id, patch),
    setData: (patch: Partial<CanvasNodeData>) => api.updateNodeData(id, patch),
    run: () => api.runNode(id),
    inspect: () => api.openInspector(id),
    running: api.runningIds.has(id),
  };
}

const targetHandle = (
  <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-border !bg-muted-foreground" />
);
const sourceHandle = (
  <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-border !bg-primary" />
);

function StatusDot({ data }: { data: CanvasNodeData }) {
  const r = data.result;
  if (!r) return null;
  if (r.status === "success")
    return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" aria-label="succeeded" />;
  if (r.status === "error")
    return <XCircle className="h-3.5 w-3.5 text-destructive" aria-label="failed" />;
  return null;
}

// ── Generic node (triggers, actions, tools, agent, control) ─────────────────
const WorkflowNodeView = memo(({ id, data, selected }: NodeProps) => {
  const d = data as CanvasNodeData;
  const { run, inspect, running } = useApi(id);
  const accent = CATEGORY_ACCENT[d.category] ?? "text-muted-foreground";
  const isTrigger = d.category === "trigger";
  const executable = d.category !== "display";

  // Compact one-line summary of the most relevant param.
  const summary =
    d.nodeType === "tool"
      ? (d.tool as string) || "tool"
      : d.nodeType === "agent"
        ? String(d.params?.prompt || "").slice(0, 40) || "no prompt"
        : Object.keys(d.params || {}).length
          ? `${Object.keys(d.params).length} param(s)`
          : "";

  return (
    <div
      className={`w-56 rounded-md border bg-card/95 text-foreground shadow-lg backdrop-blur transition ${
        selected ? "border-primary ring-1 ring-primary/40" : "border-border"
      } ${d.result?.status === "error" ? "border-destructive/60" : ""}`}
      onDoubleClick={inspect}
    >
      {!isTrigger && targetHandle}
      <div className="flex items-center gap-2 border-b border-border px-2.5 py-1.5">
        <span className="text-sm">{d.emoji ?? "⚙️"}</span>
        <span className={`flex-1 truncate text-xs font-semibold ${accent}`}>{d.label}</span>
        <StatusDot data={d} />
        <button
          type="button"
          onClick={inspect}
          className="nodrag text-muted-foreground/60 transition hover:text-foreground"
          title="Configure"
        >
          <Settings2 className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="px-2.5 py-2">
        {summary && <p className="truncate text-[11px] text-muted-foreground">{summary}</p>}
        {d.result?.error && (
          <p className="mt-1 line-clamp-2 text-[10px] text-destructive">{d.result.error}</p>
        )}
        {executable && (
          <button
            type="button"
            onClick={run}
            disabled={running}
            className="nodrag mt-2 flex w-full items-center justify-center gap-1.5 rounded-sm bg-secondary px-2 py-1 text-[11px] font-medium text-foreground transition hover:bg-primary hover:text-primary-foreground disabled:opacity-50"
          >
            {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
            Run
          </button>
        )}
      </div>
      {sourceHandle}
    </div>
  );
});
WorkflowNodeView.displayName = "WorkflowNodeView";

// ── Iframe embed ────────────────────────────────────────────────────────────
const IframeNode = memo(({ id, data, selected }: NodeProps) => {
  const d = data as CanvasNodeData;
  const { setParams, inspect } = useApi(id);
  const url = String(d.params?.url || "");
  return (
    <div
      className={`flex flex-col overflow-hidden rounded-md border bg-card shadow-lg ${
        selected ? "border-primary ring-1 ring-primary/40" : "border-border"
      }`}
      style={{ width: Number(d.width) || 420, height: Number(d.height) || 320 }}
    >
      <NodeResizer minWidth={240} minHeight={180} isVisible={selected} />
      {targetHandle}
      <div className="flex items-center gap-1.5 border-b border-border bg-card/80 px-2 py-1">
        <span className="text-xs">🌐</span>
        <input
          value={url}
          onChange={(e) => setParams({ url: e.target.value })}
          className="nodrag h-5 flex-1 rounded-sm bg-background/60 px-1.5 text-[11px] outline-none focus:ring-1 focus:ring-primary"
          placeholder="https://…"
        />
        <button type="button" onClick={() => setParams({ url })} className="nodrag text-muted-foreground hover:text-foreground" title="Reload">
          <RefreshCw className="h-3 w-3" />
        </button>
        <a href={url} target="_blank" rel="noreferrer" className="nodrag text-muted-foreground hover:text-foreground" title="Open">
          <ExternalLink className="h-3 w-3" />
        </a>
        <button type="button" onClick={inspect} className="nodrag text-muted-foreground hover:text-foreground" title="Configure">
          <Settings2 className="h-3 w-3" />
        </button>
      </div>
      {url ? (
        <iframe
          src={url}
          title={url}
          className="nodrag min-h-0 flex-1 bg-white"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
          referrerPolicy="no-referrer"
        />
      ) : (
        <div className="grid flex-1 place-items-center text-xs text-muted-foreground">Enter a URL</div>
      )}
      {sourceHandle}
    </div>
  );
});
IframeNode.displayName = "IframeNode";

// ── Web preview (link card) ─────────────────────────────────────────────────
const PreviewNode = memo(({ id, data, selected }: NodeProps) => {
  const d = data as CanvasNodeData;
  const { setParams } = useApi(id);
  const url = String(d.params?.url || "");
  let host = "";
  try {
    host = url ? new URL(url).host : "";
  } catch {
    host = url;
  }
  return (
    <div
      className={`w-64 overflow-hidden rounded-md border bg-card shadow-lg ${
        selected ? "border-primary ring-1 ring-primary/40" : "border-border"
      }`}
    >
      {targetHandle}
      <div className="flex items-center gap-2 border-b border-border px-2.5 py-1.5">
        <span className="text-xs">🔗</span>
        <span className="flex-1 truncate text-xs font-semibold text-muted-foreground">Web Preview</span>
      </div>
      <div className="p-2.5">
        <input
          value={url}
          onChange={(e) => setParams({ url: e.target.value })}
          placeholder="https://…"
          className="nodrag mb-2 w-full rounded-sm border border-border bg-background/60 px-2 py-1 text-[11px] outline-none focus:border-primary"
        />
        {host && (
          <a href={url} target="_blank" rel="noreferrer" className="nodrag flex items-center gap-2 rounded-sm border border-border bg-background/40 p-2 transition hover:bg-secondary">
            <img src={`https://www.google.com/s2/favicons?domain=${host}&sz=32`} alt="" className="h-5 w-5 rounded" />
            <span className="truncate text-xs text-foreground">{host}</span>
          </a>
        )}
      </div>
      {sourceHandle}
    </div>
  );
});
PreviewNode.displayName = "PreviewNode";

// ── Media (image / video) ───────────────────────────────────────────────────
const MediaNode = memo(({ id, data, selected }: NodeProps) => {
  const d = data as CanvasNodeData;
  const { setParams } = useApi(id);
  const url = String(d.params?.url || "");
  const isVideo = /\.(mp4|webm|mov)$/i.test(url);
  return (
    <div
      className={`flex flex-col overflow-hidden rounded-md border bg-card shadow-lg ${
        selected ? "border-primary ring-1 ring-primary/40" : "border-border"
      }`}
      style={{ width: Number(d.width) || 280, height: Number(d.height) || 220 }}
    >
      <NodeResizer minWidth={160} minHeight={120} isVisible={selected} />
      {targetHandle}
      <div className="flex items-center gap-1.5 border-b border-border px-2 py-1">
        <span className="text-xs">🖼</span>
        <input
          value={url}
          onChange={(e) => setParams({ url: e.target.value })}
          placeholder="image / video URL"
          className="nodrag h-5 flex-1 rounded-sm bg-background/60 px-1.5 text-[11px] outline-none focus:ring-1 focus:ring-primary"
        />
      </div>
      <div className="grid min-h-0 flex-1 place-items-center overflow-hidden bg-background/40">
        {!url ? (
          <span className="text-xs text-muted-foreground">Enter a URL</span>
        ) : isVideo ? (
          <video src={url} controls className="nodrag max-h-full max-w-full" />
        ) : (
          <img src={url} alt="" className="nodrag max-h-full max-w-full object-contain" />
        )}
      </div>
      {sourceHandle}
    </div>
  );
});
MediaNode.displayName = "MediaNode";

// ── Note ────────────────────────────────────────────────────────────────────
const NoteNode = memo(({ id, data, selected }: NodeProps) => {
  const d = data as CanvasNodeData;
  const { setParams } = useApi(id);
  return (
    <div
      className={`w-56 rounded-md border bg-amber-50/5 shadow-lg ${
        selected ? "border-primary ring-1 ring-primary/40" : "border-amber-500/30"
      }`}
    >
      <NodeResizer minWidth={160} minHeight={100} isVisible={selected} />
      {targetHandle}
      <textarea
        value={String(d.params?.text || "")}
        onChange={(e) => setParams({ text: e.target.value })}
        placeholder="Write a note…"
        className="nodrag h-full min-h-24 w-full resize-none rounded-md bg-transparent p-2.5 text-xs text-foreground outline-none"
      />
      {sourceHandle}
    </div>
  );
});
NoteNode.displayName = "NoteNode";

export const renderNodeTypes = {
  workflow: WorkflowNodeView,
  iframe: IframeNode,
  preview: PreviewNode,
  media: MediaNode,
  note: NoteNode,
};
