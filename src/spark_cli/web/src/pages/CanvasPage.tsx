import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Plus, Save, FolderOpen, Trash2, Loader2, Check } from "lucide-react";
import {
  api,
  type CanvasDoc,
  type CanvasScope,
  type CanvasSummary,
  type WorkspaceProject,
} from "@/lib/api";
import {
  GLOBAL_NAV_EVENT,
  takeGlobalNavTarget,
  type GlobalNavTarget,
} from "@/lib/globalNavigation";
import { nodeTypes, CanvasNodeContext } from "./canvas/nodes";
import { PALETTE, CANVAS_DND_MIME, type CanvasNodeKind } from "./canvas/types";

const LAST_KEY = "spark-canvas-last";

interface OpenCanvas {
  id: string;
  name: string;
  scope: CanvasScope;
  slug: string | null;
}

let nodeSeq = 1;
const newNodeId = () => `n${Date.now().toString(36)}_${nodeSeq++}`;

function CanvasInner() {
  const rf = useReactFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [current, setCurrent] = useState<OpenCanvas | null>(null);
  const [name, setName] = useState("Untitled");
  const [scope, setScope] = useState<CanvasScope>("global");
  const [slug, setSlug] = useState<string | null>(null);
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [saved, setSaved] = useState<CanvasSummary[]>([]);
  const [browserOpen, setBrowserOpen] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [runningNodeIds, setRunningNodeIds] = useState<Set<string>>(new Set());
  const wrapperRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  const loadedRef = useRef(false);

  // ── Node data helpers ─────────────────────────────────────────────────────
  const updateNodeData = useCallback(
    (id: string, patch: Record<string, unknown>) => {
      setNodes((nds) =>
        nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n)),
      );
    },
    [setNodes],
  );

  const setRunning = useCallback((id: string, on: boolean) => {
    setRunningNodeIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const runNode = useCallback(
    async (id: string) => {
      const node = rf.getNode(id);
      if (!node) return;
      setRunning(id, true);
      try {
        if (node.type === "chat") {
          const d = node.data as { messages?: Array<{ role: string; content: string }>; draft?: string };
          const draft = (d.draft ?? "").trim();
          if (!draft) return;
          const history = d.messages ?? [];
          const nextHistory = [...history, { role: "user", content: draft }];
          updateNodeData(id, { messages: nextHistory, draft: "" });
          const res = await api.postCanvasChat(draft, history, { slug: scope === "project" ? slug : null });
          updateNodeData(id, {
            messages: [...nextHistory, { role: "assistant", content: res.reply }],
          });
        } else if (node.type === "agent") {
          const d = node.data as { prompt?: string; model?: string };
          const prompt = (d.prompt ?? "").trim();
          if (!prompt) return;
          updateNodeData(id, { output: "" });
          const res = await api.postCanvasChat(prompt, [], {
            model: d.model || undefined,
            slug: scope === "project" ? slug : null,
          });
          updateNodeData(id, { output: res.reply });
        }
      } catch (e) {
        if (node.type === "agent") updateNodeData(id, { output: `Error: ${e}` });
        else if (node.type === "chat") {
          const d = node.data as { messages?: Array<{ role: string; content: string }> };
          updateNodeData(id, {
            messages: [...(d.messages ?? []), { role: "assistant", content: `Error: ${e}` }],
          });
        }
      } finally {
        setRunning(id, false);
      }
    },
    [rf, scope, slug, updateNodeData, setRunning],
  );

  const nodeApi = useMemo(
    () => ({ updateNodeData, runNode, runningNodeIds }),
    [updateNodeData, runNode, runningNodeIds],
  );

  const onConnect = useCallback(
    (c: Connection) => setEdges((eds) => addEdge({ ...c, animated: true }, eds)),
    [setEdges],
  );

  // ── Drag & drop from palette ──────────────────────────────────────────────
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const kind = e.dataTransfer.getData(CANVAS_DND_MIME) as CanvasNodeKind;
      const item = PALETTE.find((p) => p.kind === kind);
      if (!item) return;
      const position = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      setNodes((nds) => [
        ...nds,
        { id: newNodeId(), type: kind, position, data: item.defaults() },
      ]);
    },
    [rf, setNodes],
  );

  // ── Load projects + saved canvases ────────────────────────────────────────
  const refreshLists = useCallback(async () => {
    try {
      const [p, c] = await Promise.all([api.listWorkspaceProjects(), api.listCanvases()]);
      setProjects(p.projects);
      setSaved(c.canvases);
    } catch {
      /* ignore */
    }
  }, []);

  const loadCanvas = useCallback(
    async (target: OpenCanvas) => {
      try {
        const doc = await api.getCanvas(target.scope, target.id, target.slug);
        setNodes((doc.nodes as unknown as Node[]) ?? []);
        setEdges((doc.edges as unknown as Edge[]) ?? []);
        setCurrent(target);
        setName(doc.name || target.id);
        setScope(target.scope);
        setSlug(target.slug);
        localStorage.setItem(LAST_KEY, JSON.stringify(target));
        setBrowserOpen(false);
        if (doc.viewport) setTimeout(() => rf.setViewport(doc.viewport), 0);
      } catch {
        /* ignore */
      }
    },
    [rf, setNodes, setEdges],
  );

  // ── Initial mount: restore last canvas or honor a nav target ──────────────
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    refreshLists();
    const navTarget = takeGlobalNavTarget("canvas");
    if (navTarget && navTarget.type === "canvas") {
      void loadCanvas({
        id: navTarget.id,
        name: navTarget.id,
        scope: navTarget.scope,
        slug: navTarget.slug ?? null,
      });
      return;
    }
    const raw = localStorage.getItem(LAST_KEY);
    if (raw) {
      try {
        void loadCanvas(JSON.parse(raw) as OpenCanvas);
      } catch {
        /* ignore */
      }
    }
  }, [refreshLists, loadCanvas]);

  // ── Listen for Files-tab → Canvas navigation ──────────────────────────────
  useEffect(() => {
    const handler = (event: Event) => {
      const target = (event as CustomEvent<GlobalNavTarget>).detail;
      if (target.type !== "canvas") return;
      void loadCanvas({
        id: target.id,
        name: target.id,
        scope: target.scope,
        slug: target.slug ?? null,
      });
    };
    window.addEventListener(GLOBAL_NAV_EVENT, handler);
    return () => window.removeEventListener(GLOBAL_NAV_EVENT, handler);
  }, [loadCanvas]);

  // ── Save ──────────────────────────────────────────────────────────────────
  const doSave = useCallback(async () => {
    const id = (current?.id ?? name).trim().replace(/[^a-zA-Z0-9_\- ]/g, "").slice(0, 80) || "Untitled";
    if (scope === "project" && !slug) return;
    setSaveState("saving");
    const inst = instanceRef.current;
    const flow = inst?.toObject();
    const doc: CanvasDoc = {
      id,
      name: name.trim() || id,
      scope,
      slug: scope === "project" ? slug : null,
      nodes: (flow?.nodes ?? nodes) as CanvasDoc["nodes"],
      edges: (flow?.edges ?? edges) as CanvasDoc["edges"],
      viewport: flow?.viewport ?? { x: 0, y: 0, zoom: 1 },
      version: 1,
    };
    try {
      await api.saveCanvas(doc);
      const target: OpenCanvas = { id, name: doc.name, scope, slug: doc.slug };
      setCurrent(target);
      localStorage.setItem(LAST_KEY, JSON.stringify(target));
      void refreshLists();
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 1500);
    } catch {
      setSaveState("idle");
    }
  }, [current, name, scope, slug, nodes, edges, refreshLists]);

  // ── Debounced autosave once a canvas has been saved at least once ─────────
  useEffect(() => {
    if (!current) return;
    const t = setTimeout(() => void doSave(), 1200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  const newCanvas = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setCurrent(null);
    setName("Untitled");
    localStorage.removeItem(LAST_KEY);
  }, [setNodes, setEdges]);

  const deleteCurrent = useCallback(async () => {
    if (!current) {
      newCanvas();
      return;
    }
    try {
      await api.deleteCanvas(current.scope, current.id, current.slug);
    } catch {
      /* ignore */
    }
    newCanvas();
    void refreshLists();
  }, [current, newCanvas, refreshLists]);

  return (
    <div className="flex h-full min-h-0 overflow-hidden border-t border-border">
      {/* Palette */}
      <aside className="flex w-44 shrink-0 flex-col gap-1.5 border-r border-border bg-card/50 p-2.5">
        <div className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
          Tools
        </div>
        {PALETTE.map((item) => {
          const Icon = item.icon;
          return (
            <div
              key={item.kind}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(CANVAS_DND_MIME, item.kind);
                e.dataTransfer.effectAllowed = "move";
              }}
              title={item.description}
              className="flex cursor-grab items-center gap-2 rounded-sm border border-border bg-background/60 px-2 py-1.5 text-xs text-foreground transition hover:border-primary/50 hover:bg-secondary active:cursor-grabbing"
            >
              <Icon className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="font-medium">{item.label}</span>
            </div>
          );
        })}
        <p className="mt-1 px-1 text-[10px] leading-snug text-muted-foreground/50">
          Drag a tool onto the canvas.
        </p>
      </aside>

      {/* Canvas + toolbar */}
      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-card/40 px-3 py-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-7 w-40 rounded-sm border border-border bg-background/60 px-2 text-sm outline-none focus:border-primary"
            placeholder="Canvas name"
          />
          <select
            value={scope === "project" && slug ? `project:${slug}` : "global"}
            onChange={(e) => {
              const v = e.target.value;
              if (v === "global") {
                setScope("global");
                setSlug(null);
              } else {
                setScope("project");
                setSlug(v.slice("project:".length));
              }
            }}
            className="h-7 rounded-sm border border-border bg-background/60 px-2 text-sm outline-none focus:border-primary"
          >
            <option value="global">Global</option>
            {projects.map((p) => (
              <option key={p.slug} value={`project:${p.slug}`}>
                {p.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void doSave()}
            disabled={saveState === "saving"}
            className="flex h-7 items-center gap-1.5 rounded-sm bg-primary px-2.5 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
          >
            {saveState === "saving" ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : saveState === "saved" ? (
              <Check className="h-3 w-3" />
            ) : (
              <Save className="h-3 w-3" />
            )}
            Save
          </button>
          <button
            type="button"
            onClick={() => {
              void refreshLists();
              setBrowserOpen((o) => !o);
            }}
            className="flex h-7 items-center gap-1.5 rounded-sm border border-border px-2.5 text-xs text-muted-foreground transition hover:bg-secondary hover:text-foreground"
          >
            <FolderOpen className="h-3 w-3" /> Open
          </button>
          <button
            type="button"
            onClick={newCanvas}
            className="flex h-7 items-center gap-1.5 rounded-sm border border-border px-2.5 text-xs text-muted-foreground transition hover:bg-secondary hover:text-foreground"
          >
            <Plus className="h-3 w-3" /> New
          </button>
          <button
            type="button"
            onClick={() => void deleteCurrent()}
            className="ml-auto flex h-7 items-center gap-1.5 rounded-sm border border-border px-2.5 text-xs text-muted-foreground transition hover:bg-destructive/15 hover:text-destructive"
          >
            <Trash2 className="h-3 w-3" /> Delete
          </button>
        </div>

        {/* Open browser dropdown */}
        {browserOpen && (
          <div className="absolute right-3 top-12 z-20 max-h-80 w-72 overflow-y-auto rounded-md border border-border bg-popover p-1.5 shadow-2xl">
            {saved.length === 0 && (
              <p className="px-2 py-3 text-center text-xs text-muted-foreground">No saved canvases.</p>
            )}
            {saved.map((c) => (
              <button
                key={`${c.scope}:${c.slug ?? ""}:${c.id}`}
                type="button"
                onClick={() => void loadCanvas({ id: c.id, name: c.name, scope: c.scope, slug: c.slug })}
                className="flex w-full items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-left text-xs text-foreground transition hover:bg-secondary"
              >
                <span className="truncate font-medium">{c.name}</span>
                <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">
                  {c.scope === "project" ? c.slug : "global"}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* Flow */}
        <div ref={wrapperRef} className="min-h-0 flex-1" onDrop={onDrop} onDragOver={onDragOver}>
          <CanvasNodeContext.Provider value={nodeApi}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onInit={(inst) => (instanceRef.current = inst)}
              nodeTypes={nodeTypes}
              fitView
              proOptions={{ hideAttribution: true }}
              deleteKeyCode={["Backspace", "Delete"]}
              className="bg-background"
            >
              <Background variant={BackgroundVariant.Dots} gap={18} size={1} className="!bg-background" />
              <Controls className="!border-border" />
              <MiniMap pannable zoomable className="!bg-card" />
            </ReactFlow>
          </CanvasNodeContext.Provider>
        </div>
      </div>
    </div>
  );
}

export default function CanvasPage() {
  return (
    <ReactFlowProvider>
      <CanvasInner />
    </ReactFlowProvider>
  );
}
