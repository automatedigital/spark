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
import { Plus, Save, FolderOpen, Trash2, Loader2, Check, Play, Search } from "lucide-react";
import {
  api,
  type CanvasDoc,
  type CanvasScope,
  type CanvasSummary,
  type WorkflowNodeType,
  type WorkspaceProject,
} from "@/lib/api";
import {
  GLOBAL_NAV_EVENT,
  takeGlobalNavTarget,
  type GlobalNavTarget,
} from "@/lib/globalNavigation";
import { renderNodeTypes, CanvasNodeContext } from "./canvas/render";
import { CANVAS_DND_MIME, renderTypeFor, defaultParams, type CanvasNodeData } from "./canvas/types";
import Inspector from "./canvas/Inspector";

const LAST_KEY = "spark-canvas-last";

interface OpenCanvas {
  id: string;
  name: string;
  scope: CanvasScope;
  slug: string | null;
}

let nodeSeq = 1;
const newNodeId = () => `n${Date.now().toString(36)}_${nodeSeq++}`;

/** Build the engine doc from React Flow nodes/edges. */
function toEngineDoc(base: OpenCanvas | null, name: string, scope: CanvasScope, slug: string | null, nodes: Node[], edges: Edge[]): CanvasDoc {
  const id = (base?.id ?? name).trim().replace(/[^a-zA-Z0-9_\- ]/g, "").slice(0, 80) || "Untitled";
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
        data: { label: d.label, emoji: d.emoji, category: d.category, tool: d.tool, width: n.width, height: n.height },
      };
    }) as CanvasDoc["nodes"],
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target })) as CanvasDoc["edges"],
    viewport: { x: 0, y: 0, zoom: 1 },
    version: 2,
  };
}

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
  const [nodeTypes, setNodeTypes] = useState<WorkflowNodeType[]>([]);
  const [browserOpen, setBrowserOpen] = useState(false);
  const [openOpen, setOpenOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");
  const [runningIds, setRunningIds] = useState<Set<string>>(new Set());
  const [runningAll, setRunningAll] = useState(false);
  const [inspectorId, setInspectorId] = useState<string | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  const loadedRef = useRef(false);

  // ── Node data helpers ─────────────────────────────────────────────────────
  const updateNodeData = useCallback(
    (id: string, patch: Partial<CanvasNodeData>) =>
      setNodes((nds) => nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...patch } } : n))),
    [setNodes],
  );
  const updateParams = useCallback(
    (id: string, patch: Record<string, unknown>) =>
      setNodes((nds) =>
        nds.map((n) =>
          n.id === id ? { ...n, data: { ...n.data, params: { ...(n.data as CanvasNodeData).params, ...patch } } } : n,
        ),
      ),
    [setNodes],
  );

  const setRunning = useCallback((id: string, on: boolean) => {
    setRunningIds((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);

  const applyResults = useCallback(
    (results: { nodeId: string; status: string; items: unknown[]; error: string | null; durationMs: number }[]) => {
      setNodes((nds) =>
        nds.map((n) => {
          const r = results.find((x) => x.nodeId === n.id);
          return r ? { ...n, data: { ...n.data, result: r } } : n;
        }),
      );
    },
    [setNodes],
  );

  const buildDoc = useCallback(
    () => toEngineDoc(current, name, scope, slug, rf.getNodes(), rf.getEdges()),
    [current, name, scope, slug, rf],
  );

  const runNode = useCallback(
    async (id: string) => {
      setRunning(id, true);
      try {
        const res = await api.runWorkflowNode(buildDoc(), id);
        applyResults(res.nodes);
      } catch (e) {
        applyResults([{ nodeId: id, status: "error", items: [], error: String(e), durationMs: 0 }]);
      } finally {
        setRunning(id, false);
      }
    },
    [buildDoc, applyResults, setRunning],
  );

  const runAll = useCallback(async () => {
    setRunningAll(true);
    try {
      const res = await api.runWorkflow(buildDoc(), "manual");
      applyResults(res.nodes);
    } catch {
      /* surfaced per-node */
    } finally {
      setRunningAll(false);
    }
  }, [buildDoc, applyResults]);

  const nodeApi = useMemo(
    () => ({ updateNodeData, updateParams, runNode, openInspector: setInspectorId, runningIds }),
    [updateNodeData, updateParams, runNode, runningIds],
  );

  const onConnect = useCallback(
    (c: Connection) => setEdges((eds) => addEdge({ ...c, animated: true }, eds)),
    [setEdges],
  );

  // ── Add a node from the catalog ───────────────────────────────────────────
  const addNode = useCallback(
    (t: WorkflowNodeType, position: { x: number; y: number }) => {
      const data: CanvasNodeData = {
        nodeType: t.type,
        label: t.label,
        emoji: t.emoji,
        category: t.category,
        tool: t.tool,
        schema: t.schema,
        description: t.description,
        params: defaultParams(t),
        result: null,
      };
      setNodes((nds) => [...nds, { id: newNodeId(), type: renderTypeFor(t.type), position, data }]);
    },
    [setNodes],
  );

  // ── Drag & drop from the node browser ─────────────────────────────────────
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);
  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const raw = e.dataTransfer.getData(CANVAS_DND_MIME);
      if (!raw) return;
      const t = JSON.parse(raw) as WorkflowNodeType;
      addNode(t, rf.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
    },
    [rf, addNode],
  );

  // ── Lists & catalog ───────────────────────────────────────────────────────
  const refreshLists = useCallback(async () => {
    try {
      const [p, c] = await Promise.all([api.listWorkspaceProjects(), api.listCanvases()]);
      setProjects(p.projects);
      setSaved(c.canvases);
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    api.getWorkflowNodeTypes().then((r) => setNodeTypes(r.nodeTypes)).catch(() => {});
  }, []);

  const loadCanvas = useCallback(
    async (target: OpenCanvas) => {
      try {
        const doc = await api.getCanvas(target.scope, target.id, target.slug);
        const loadedNodes: Node[] = (doc.nodes ?? []).map((n) => {
          const dn = n as unknown as { id: string; type: string; position: { x: number; y: number }; params?: Record<string, unknown>; data?: Record<string, unknown> };
          const d = (dn.data ?? {}) as Record<string, unknown>;
          const data: CanvasNodeData = {
            nodeType: dn.type,
            label: String(d.label ?? dn.type),
            emoji: d.emoji as string | undefined,
            category: (d.category as CanvasNodeData["category"]) ?? "action",
            tool: d.tool as string | undefined,
            params: dn.params ?? {},
            result: null,
          };
          return {
            id: dn.id,
            type: renderTypeFor(dn.type),
            position: dn.position ?? { x: 0, y: 0 },
            data,
            width: typeof d.width === "number" ? d.width : undefined,
            height: typeof d.height === "number" ? d.height : undefined,
          };
        });
        setNodes(loadedNodes);
        setEdges((doc.edges as unknown as Edge[]) ?? []);
        setCurrent(target);
        setName(doc.name || target.id);
        setScope(target.scope);
        setSlug(target.slug);
        localStorage.setItem(LAST_KEY, JSON.stringify(target));
        setOpenOpen(false);
        setInspectorId(null);
      } catch {
        /* ignore */
      }
    },
    [setNodes, setEdges],
  );

  // ── Mount: restore last / honor nav target ────────────────────────────────
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    refreshLists();
    const navTarget = takeGlobalNavTarget("canvas");
    if (navTarget && navTarget.type === "canvas") {
      void loadCanvas({ id: navTarget.id, name: navTarget.id, scope: navTarget.scope, slug: navTarget.slug ?? null });
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

  useEffect(() => {
    const handler = (event: Event) => {
      const target = (event as CustomEvent<GlobalNavTarget>).detail;
      if (target.type !== "canvas") return;
      void loadCanvas({ id: target.id, name: target.id, scope: target.scope, slug: target.slug ?? null });
    };
    window.addEventListener(GLOBAL_NAV_EVENT, handler);
    return () => window.removeEventListener(GLOBAL_NAV_EVENT, handler);
  }, [loadCanvas]);

  // ── Save / autosave ───────────────────────────────────────────────────────
  const doSave = useCallback(async () => {
    if (scope === "project" && !slug) return;
    setSaveState("saving");
    const doc = buildDoc();
    try {
      await api.saveCanvas(doc);
      const target: OpenCanvas = { id: doc.id, name: doc.name, scope, slug: doc.slug };
      setCurrent(target);
      localStorage.setItem(LAST_KEY, JSON.stringify(target));
      void refreshLists();
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 1500);
    } catch {
      setSaveState("idle");
    }
  }, [scope, slug, buildDoc, refreshLists]);

  useEffect(() => {
    if (!current) return;
    const t = setTimeout(() => void doSave(), 1500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  const newCanvas = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setCurrent(null);
    setName("Untitled");
    setInspectorId(null);
    localStorage.removeItem(LAST_KEY);
  }, [setNodes, setEdges]);

  const deleteCurrent = useCallback(async () => {
    if (current) {
      try {
        await api.deleteCanvas(current.scope, current.id, current.slug);
      } catch {
        /* ignore */
      }
    }
    newCanvas();
    void refreshLists();
  }, [current, newCanvas, refreshLists]);

  // ── Node browser grouping ─────────────────────────────────────────────────
  const grouped = useMemo(() => {
    const q = search.toLowerCase();
    const filtered = nodeTypes.filter(
      (t) => !q || t.label.toLowerCase().includes(q) || (t.toolset ?? "").toLowerCase().includes(q),
    );
    const groups: Record<string, WorkflowNodeType[]> = {};
    for (const t of filtered) {
      const g = t.category === "action" ? `tools · ${t.toolset ?? "core"}` : t.category;
      (groups[g] ??= []).push(t);
    }
    return Object.entries(groups).sort((a, b) => a[0].localeCompare(b[0]));
  }, [nodeTypes, search]);

  const inspectorNode = inspectorId ? nodes.find((n) => n.id === inspectorId) ?? null : null;

  return (
    <div className="flex h-full min-h-0 overflow-hidden border-t border-border">
      {/* Canvas + toolbar */}
      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-card/40 px-3 py-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-7 w-36 rounded-sm border border-border bg-background/60 px-2 text-sm outline-none focus:border-primary"
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
            onClick={() => void runAll()}
            disabled={runningAll}
            className="flex h-7 items-center gap-1.5 rounded-sm bg-emerald-600 px-2.5 text-xs font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-50"
          >
            {runningAll ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
            Run
          </button>
          <button
            type="button"
            onClick={() => setBrowserOpen((o) => !o)}
            className="flex h-7 items-center gap-1.5 rounded-sm bg-primary px-2.5 text-xs font-medium text-primary-foreground transition hover:bg-primary/90"
          >
            <Plus className="h-3 w-3" /> Add node
          </button>

          <button
            type="button"
            onClick={() => void doSave()}
            disabled={saveState === "saving"}
            className="flex h-7 items-center gap-1.5 rounded-sm border border-border px-2.5 text-xs text-muted-foreground transition hover:bg-secondary hover:text-foreground disabled:opacity-50"
          >
            {saveState === "saving" ? <Loader2 className="h-3 w-3 animate-spin" /> : saveState === "saved" ? <Check className="h-3 w-3" /> : <Save className="h-3 w-3" />}
            Save
          </button>
          <button
            type="button"
            onClick={() => {
              void refreshLists();
              setOpenOpen((o) => !o);
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

        {/* Open browser */}
        {openOpen && (
          <div className="absolute right-3 top-12 z-20 max-h-80 w-72 overflow-y-auto rounded-md border border-border bg-popover p-1.5 shadow-2xl">
            {saved.length === 0 && <p className="px-2 py-3 text-center text-xs text-muted-foreground">No saved canvases.</p>}
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
              nodeTypes={renderNodeTypes}
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

      {/* Node browser drawer */}
      {browserOpen && (
        <aside className="flex w-64 shrink-0 flex-col border-l border-border bg-card/70 backdrop-blur-xl">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <Search className="h-3.5 w-3.5 text-muted-foreground" />
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search nodes & tools…"
              className="h-6 flex-1 bg-transparent text-xs outline-none"
            />
            <button type="button" onClick={() => setBrowserOpen(false)} className="text-muted-foreground hover:text-foreground text-xs">
              ✕
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {grouped.map(([group, items]) => (
              <div key={group} className="mb-2">
                <div className="px-1 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">{group}</div>
                {items.map((t) => (
                  <div
                    key={`${t.type}:${t.tool ?? t.label}`}
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData(CANVAS_DND_MIME, JSON.stringify(t));
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    onClick={() => addNode(t, rf.screenToFlowPosition({ x: window.innerWidth / 2, y: window.innerHeight / 2 }))}
                    title={t.description || t.label}
                    className="flex cursor-grab items-center gap-2 rounded-sm border border-transparent px-2 py-1.5 text-xs text-foreground transition hover:border-border hover:bg-secondary active:cursor-grabbing"
                  >
                    <span>{t.emoji ?? "⚙️"}</span>
                    <span className="truncate">{t.label}</span>
                  </div>
                ))}
              </div>
            ))}
            {grouped.length === 0 && <p className="px-2 py-3 text-center text-xs text-muted-foreground">No matching nodes.</p>}
          </div>
        </aside>
      )}

      {/* Inspector drawer */}
      {inspectorNode && (
        <Inspector
          node={inspectorNode}
          nodes={nodes}
          edges={edges}
          onClose={() => setInspectorId(null)}
          onParam={(k, v) => updateParams(inspectorNode.id, { [k]: v })}
          onRun={() => void runNode(inspectorNode.id)}
          running={runningIds.has(inspectorNode.id)}
        />
      )}
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
