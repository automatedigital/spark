/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, memo } from "react";
import { Handle, Position, NodeResizer, type NodeProps } from "@xyflow/react";
import { Loader2, Play, RefreshCw, ExternalLink, Settings2, CheckCircle2, XCircle } from "lucide-react";
import { Markdown } from "@/components/Markdown";
import { api } from "@/lib/api";
import { CATEGORY_ACCENT, type CanvasNodeData } from "./types";

export interface CanvasNodeApi {
  updateNodeData: (id: string, patch: Partial<CanvasNodeData>) => void;
  updateParams: (id: string, patch: Record<string, unknown>) => void;
  runNode: (id: string) => void;
  openInspector: (id: string) => void;
  runningIds: Set<string>;
  canvasId?: string;
  scope?: string;
  slug?: string | null;
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

function domainAllowed(url: string, allowCsv: unknown, blockCsv: unknown): boolean {
  if (!url) return true;
  let host = "";
  try {
    host = new URL(url).hostname;
  } catch {
    return false;
  }
  const allow = String(allowCsv || "").split(",").map((s) => s.trim()).filter(Boolean);
  const block = String(blockCsv || "").split(",").map((s) => s.trim()).filter(Boolean);
  const matches = (domain: string) => host === domain || host.endsWith(`.${domain}`);
  if (block.some(matches)) return false;
  return allow.length === 0 || allow.some(matches);
}

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
  const allowed = domainAllowed(url, d.params?.allowDomains, d.params?.blockDomains);
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
      {url && allowed ? (
        <iframe
          src={url}
          title={url}
          className="nodrag min-h-0 flex-1 bg-white"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
          referrerPolicy="no-referrer"
        />
      ) : url ? (
        <div className="grid flex-1 place-items-center px-4 text-center text-xs text-destructive">Domain blocked by this embed node.</div>
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
  const meta = d.result?.items?.[0]?.json as Record<string, unknown> | undefined;
  const title = String(meta?.title || host || "Web Preview");
  const description = String(meta?.description || "");
  const image = String(meta?.image || "");
  const favicon = String(meta?.favicon || "");
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
          <a href={url} target="_blank" rel="noreferrer" className="nodrag block overflow-hidden rounded-sm border border-border bg-background/40 transition hover:bg-secondary">
            {image && <img src={image} alt="" className="h-24 w-full object-cover" />}
            <div className="flex items-start gap-2 p-2">
              <img src={favicon || `https://www.google.com/s2/favicons?domain=${host}&sz=32`} alt="" className="mt-0.5 h-5 w-5 rounded" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-foreground">{title}</span>
                {description && <span className="mt-0.5 line-clamp-2 text-[10px] text-muted-foreground">{description}</span>}
              </span>
            </div>
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
  const isPdf = /\.pdf(?:$|\?)/i.test(url);
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
        ) : isPdf ? (
          <iframe src={url} title={url} className="nodrag h-full w-full bg-white" />
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
  const text = String(d.params?.text || "");
  return (
    <div
      className={`w-56 rounded-md border bg-amber-50/5 shadow-lg ${
        selected ? "border-primary ring-1 ring-primary/40" : "border-amber-500/30"
      }`}
    >
      <NodeResizer minWidth={160} minHeight={100} isVisible={selected} />
      {targetHandle}
      {selected ? (
        <textarea
          value={text}
          onChange={(e) => setParams({ text: e.target.value })}
          placeholder="Write a note…"
          className="nodrag h-full min-h-24 w-full resize-none rounded-md bg-transparent p-2.5 text-xs text-foreground outline-none"
        />
      ) : (
        <div className="nodrag max-h-64 min-h-24 overflow-auto p-2.5 text-xs">
          <Markdown content={text || " "} />
        </div>
      )}
      {sourceHandle}
    </div>
  );
});
NoteNode.displayName = "NoteNode";

const RenderOutputNode = memo(({ id, data, selected }: NodeProps) => {
  const d = data as CanvasNodeData;
  const { inspect } = useApi(id);
  const result = d.result?.items?.[0]?.json as Record<string, unknown> | undefined;
  const content = result?.content ?? d.params?.content ?? "";
  const format = String(result?.format || d.params?.format || "text");
  const text = typeof content === "string" ? content : JSON.stringify(content, null, 2);
  return (
    <div
      className={`w-72 overflow-hidden rounded-md border bg-card shadow-lg ${
        selected ? "border-primary ring-1 ring-primary/40" : "border-border"
      }`}
    >
      {targetHandle}
      <div className="flex items-center gap-2 border-b border-border px-2.5 py-1.5">
        <span className="text-xs">🪟</span>
        <span className="flex-1 truncate text-xs font-semibold text-muted-foreground">Render Output</span>
        <button type="button" onClick={inspect} className="nodrag text-muted-foreground hover:text-foreground" title="Configure">
          <Settings2 className="h-3 w-3" />
        </button>
      </div>
      <div className="nodrag max-h-64 overflow-auto p-2.5 text-xs">
        {format === "markdown" ? <Markdown content={text} /> : <pre className="whitespace-pre-wrap font-mono text-[11px]">{text}</pre>}
      </div>
      {sourceHandle}
    </div>
  );
});
RenderOutputNode.displayName = "RenderOutputNode";

const ActionsNode = memo(({ id, data, selected }: NodeProps) => {
  const d = data as CanvasNodeData;
  const ctx = useContext(CanvasNodeContext);
  const prompt = String(d.params?.prompt ?? "");
  const options = Array.isArray(d.params?.options) ? (d.params!.options as string[]) : [];
  const widgetId = String(d.params?.widget_id ?? id);
  const [chosen, setChosen] = useState<string | null>(null);

  const click = (value: string) => {
    if (chosen) return;
    setChosen(value);
    void api
      .canvasInteract({
        scope: ctx.scope ?? "global",
        slug: ctx.slug ?? null,
        canvas_id: ctx.canvasId ?? "",
        widget_id: widgetId,
        value,
      })
      .catch(() => setChosen(null));
  };

  return (
    <div className={`w-64 overflow-hidden rounded-md border bg-card shadow-lg ${selected ? "border-primary ring-1 ring-primary/40" : "border-border"}`}>
      {targetHandle}
      <div className="flex items-center gap-2 border-b border-border px-2.5 py-1.5">
        <span className="text-xs">🔘</span>
        <span className="flex-1 truncate text-xs font-semibold text-muted-foreground">Actions</span>
      </div>
      <div className="nodrag space-y-2 p-2.5">
        {prompt && <p className="text-xs text-foreground/90">{prompt}</p>}
        <div className="flex flex-col gap-1.5">
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              disabled={!!chosen}
              onClick={() => click(opt)}
              className={`rounded-md border px-2.5 py-1.5 text-left text-xs transition ${
                chosen === opt
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-background text-foreground hover:border-primary/50 hover:bg-secondary disabled:opacity-40"
              }`}
            >
              {opt}
            </button>
          ))}
        </div>
        {chosen && <p className="text-[10px] text-muted-foreground/60">Sent: {chosen}</p>}
      </div>
      {sourceHandle}
    </div>
  );
});
ActionsNode.displayName = "ActionsNode";

export const renderNodeTypes = {
  workflow: WorkflowNodeView,
  iframe: IframeNode,
  preview: PreviewNode,
  media: MediaNode,
  note: NoteNode,
  render: RenderOutputNode,
  actions: ActionsNode,
};
