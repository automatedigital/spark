/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { Loader2, Play } from "lucide-react";
import { PALETTE_BY_KIND, type CanvasNodeKind } from "./types";

// ── Per-canvas wiring shared with every node via context ────────────────────
export interface CanvasNodeApi {
  updateNodeData: (id: string, patch: Record<string, unknown>) => void;
  runNode: (id: string) => void;
  runningNodeIds: Set<string>;
}

const noop = () => {};
export const CanvasNodeContext = createContext<CanvasNodeApi>({
  updateNodeData: noop,
  runNode: noop,
  runningNodeIds: new Set(),
});

function useNodeApi(id: string) {
  const api = useContext(CanvasNodeContext);
  return {
    update: (patch: Record<string, unknown>) => api.updateNodeData(id, patch),
    run: () => api.runNode(id),
    running: api.runningNodeIds.has(id),
  };
}

const inHandle = (
  <Handle type="target" position={Position.Left} className="!h-2.5 !w-2.5 !border-border !bg-muted-foreground" />
);
const outHandle = (
  <Handle type="source" position={Position.Right} className="!h-2.5 !w-2.5 !border-border !bg-primary" />
);

function NodeShell({
  kind,
  selected,
  children,
  accent,
}: {
  kind: CanvasNodeKind;
  selected?: boolean;
  children: React.ReactNode;
  accent?: string;
}) {
  const item = PALETTE_BY_KIND[kind];
  const Icon = item.icon;
  return (
    <div
      className={`w-60 rounded-md border bg-card/95 text-foreground shadow-lg backdrop-blur transition ${
        selected ? "border-primary ring-1 ring-primary/40" : "border-border"
      }`}
    >
      <div className="flex items-center gap-2 border-b border-border px-2.5 py-1.5">
        <Icon className={`h-3.5 w-3.5 ${accent ?? "text-muted-foreground"}`} />
        <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {item.label}
        </span>
      </div>
      <div className="p-2.5">{children}</div>
    </div>
  );
}

// ── Note ────────────────────────────────────────────────────────────────────
const NoteNode = memo(({ id, data, selected }: NodeProps) => {
  const { update } = useNodeApi(id);
  return (
    <NodeShell kind="note" selected={selected} accent="text-amber-400">
      <textarea
        value={String((data as { text?: string }).text ?? "")}
        onChange={(e) => update({ text: e.target.value })}
        placeholder="Write a note…"
        className="nodrag h-24 w-full resize-none rounded-sm border border-border bg-background/60 p-2 text-xs outline-none focus:border-primary"
      />
    </NodeShell>
  );
});
NoteNode.displayName = "NoteNode";

// ── Chat (canvas-local) ─────────────────────────────────────────────────────
interface ChatMsg {
  role: string;
  content: string;
}
const ChatNode = memo(({ id, data, selected }: NodeProps) => {
  const { update, run, running } = useNodeApi(id);
  const d = data as { messages?: ChatMsg[]; draft?: string };
  const messages = d.messages ?? [];
  return (
    <NodeShell kind="chat" selected={selected} accent="text-sky-400">
      {inHandle}
      <div className="flex max-h-40 flex-col gap-1.5 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <p className="text-[11px] italic text-muted-foreground/60">No messages yet.</p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`rounded-sm px-2 py-1 text-[11px] ${
              m.role === "user"
                ? "bg-primary/10 text-foreground"
                : "bg-secondary/60 text-muted-foreground"
            }`}
          >
            {m.content}
          </div>
        ))}
        {running && (
          <div className="flex items-center gap-1.5 px-2 py-1 text-[11px] text-muted-foreground">
            <Loader2 className="h-3 w-3 animate-spin" /> thinking…
          </div>
        )}
      </div>
      <div className="mt-2 flex items-end gap-1.5">
        <textarea
          value={d.draft ?? ""}
          onChange={(e) => update({ draft: e.target.value })}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!running && (d.draft ?? "").trim()) run();
            }
          }}
          placeholder="Message…"
          className="nodrag h-9 flex-1 resize-none rounded-sm border border-border bg-background/60 p-1.5 text-xs outline-none focus:border-primary"
        />
        <button
          type="button"
          onClick={run}
          disabled={running || !(d.draft ?? "").trim()}
          className="nodrag grid h-9 w-9 shrink-0 place-items-center rounded-sm bg-primary text-primary-foreground transition hover:bg-primary/90 disabled:opacity-40"
          title="Send"
        >
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
        </button>
      </div>
      {outHandle}
    </NodeShell>
  );
});
ChatNode.displayName = "ChatNode";

// ── Agent ───────────────────────────────────────────────────────────────────
const AgentNode = memo(({ id, data, selected }: NodeProps) => {
  const { update, run, running } = useNodeApi(id);
  const d = data as { prompt?: string; model?: string; output?: string };
  return (
    <NodeShell kind="agent" selected={selected} accent="text-violet-400">
      {inHandle}
      <input
        value={d.model ?? ""}
        onChange={(e) => update({ model: e.target.value })}
        placeholder="model (optional)"
        className="nodrag mb-1.5 w-full rounded-sm border border-border bg-background/60 px-2 py-1 text-[11px] outline-none focus:border-primary"
      />
      <textarea
        value={d.prompt ?? ""}
        onChange={(e) => update({ prompt: e.target.value })}
        placeholder="Prompt…"
        className="nodrag h-16 w-full resize-none rounded-sm border border-border bg-background/60 p-2 text-xs outline-none focus:border-primary"
      />
      <button
        type="button"
        onClick={run}
        disabled={running || !(d.prompt ?? "").trim()}
        className="nodrag mt-2 flex w-full items-center justify-center gap-1.5 rounded-sm bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-40"
      >
        {running ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
        Run
      </button>
      {d.output && (
        <div className="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap rounded-sm bg-secondary/60 p-2 text-[11px] text-muted-foreground">
          {d.output}
        </div>
      )}
      {outHandle}
    </NodeShell>
  );
});
AgentNode.displayName = "AgentNode";

// ── Tool ────────────────────────────────────────────────────────────────────
const ToolNode = memo(({ id, data, selected }: NodeProps) => {
  const { update } = useNodeApi(id);
  const d = data as { tool?: string; args?: string; output?: string };
  return (
    <NodeShell kind="tool" selected={selected} accent="text-emerald-400">
      {inHandle}
      <input
        value={d.tool ?? ""}
        onChange={(e) => update({ tool: e.target.value })}
        placeholder="tool name"
        className="nodrag mb-1.5 w-full rounded-sm border border-border bg-background/60 px-2 py-1 text-[11px] outline-none focus:border-primary"
      />
      <textarea
        value={d.args ?? ""}
        onChange={(e) => update({ args: e.target.value })}
        placeholder='{"arg": "value"}'
        className="nodrag h-14 w-full resize-none rounded-sm border border-border bg-background/60 p-2 font-mono text-[11px] outline-none focus:border-primary"
      />
      {outHandle}
    </NodeShell>
  );
});
ToolNode.displayName = "ToolNode";

// ── Input / Output ──────────────────────────────────────────────────────────
const InputNode = memo(({ id, data, selected }: NodeProps) => {
  const { update } = useNodeApi(id);
  const d = data as { value?: string };
  return (
    <NodeShell kind="input" selected={selected}>
      <input
        value={d.value ?? ""}
        onChange={(e) => update({ value: e.target.value })}
        placeholder="value"
        className="nodrag w-full rounded-sm border border-border bg-background/60 px-2 py-1 text-xs outline-none focus:border-primary"
      />
      {outHandle}
    </NodeShell>
  );
});
InputNode.displayName = "InputNode";

const OutputNode = memo(({ data, selected }: NodeProps) => {
  const d = data as { value?: string };
  return (
    <NodeShell kind="output" selected={selected}>
      {inHandle}
      <div className="min-h-8 whitespace-pre-wrap rounded-sm bg-secondary/60 p-2 text-xs text-muted-foreground">
        {d.value || <span className="italic text-muted-foreground/50">(empty)</span>}
      </div>
    </NodeShell>
  );
});
OutputNode.displayName = "OutputNode";

export const nodeTypes = {
  note: NoteNode,
  chat: ChatNode,
  agent: AgentNode,
  tool: ToolNode,
  input: InputNode,
  output: OutputNode,
};
