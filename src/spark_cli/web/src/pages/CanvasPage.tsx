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
  type EdgeMouseHandler,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Plus, Save, FolderOpen, Trash2, Loader2, Check, Play, Search, Square, History, Copy, Undo2, Redo2 } from "lucide-react";
import {
  api,
  type CanvasScope,
  type CanvasSummary,
  type WorkflowExecutionSummary,
  type WorkflowNodeType,
  type WorkspaceProject,
} from "@/lib/api";
import {
  GLOBAL_NAV_EVENT,
  takeGlobalNavTarget,
  type GlobalNavTarget,
} from "@/lib/globalNavigation";
import { renderNodeTypes, CanvasNodeContext } from "./canvas/render";
import { CANVAS_DND_MIME, type CanvasNodeData } from "./canvas/types";
import { canvasIdentityKey, fromCanvasDoc, makeCanvasNode, toCanvasDoc } from "./canvas/model";
import { useNodeCatalog } from "./canvas/useNodeCatalog";
import { useCanvasShortcuts } from "./canvas/useCanvasShortcuts";
import { useCanvasHistory } from "./canvas/useCanvasHistory";
import Inspector from "./canvas/Inspector";
import { useEventBus } from "@/hooks/useEventBus";

const LAST_KEY = "spark-canvas-last";

interface OpenCanvas {
  id: string;
  name: string;
  scope: CanvasScope;
  slug: string | null;
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
  const [browserOpen, setBrowserOpen] = useState(false);
  const [openOpen, setOpenOpen] = useState(false);
  const [search, setSearch] = useState("");
  const { nodeTypes, grouped } = useNodeCatalog(search);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "conflict">("idle");
  const [lastRevision, setLastRevision] = useState<string | null>(null);
  const [runningIds, setRunningIds] = useState<Set<string>>(new Set());
  const [runningAll, setRunningAll] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [lastRunStatus, setLastRunStatus] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [executions, setExecutions] = useState<WorkflowExecutionSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [edgePreview, setEdgePreview] = useState<{ x: number; y: number; edge: Edge; items: unknown[] } | null>(null);
  const [inspectorId, setInspectorId] = useState<string | null>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const instanceRef = useRef<ReactFlowInstance<Node, Edge> | null>(null);
  const loadedRef = useRef(false);
  const runEventSourceRef = useRef<EventSource | null>(null);
  const activeRunCanvasKeyRef = useRef<string | null>(null);
  const { remember, undo, redo, canUndo, canRedo } = useCanvasHistory(setNodes, setEdges);

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
    (expectedRevision: string | null = lastRevision) =>
      toCanvasDoc(current, name, scope, slug, rf.getNodes(), rf.getEdges(), rf.getViewport(), expectedRevision),
    [current, name, scope, slug, rf, lastRevision],
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

  const refreshExecutions = useCallback(async () => {
    const doc = buildDoc();
    try {
      const res = await api.listWorkflowExecutions(doc.id, doc.scope, doc.slug);
      setExecutions(res.executions);
    } catch {
      setExecutions([]);
    }
  }, [buildDoc]);

  const runAll = useCallback(async () => {
    setRunningAll(true);
    setLastRunStatus("running");
    const doc = buildDoc();
    const runCanvasKey = canvasIdentityKey(doc.scope, doc.slug, doc.id);
    activeRunCanvasKeyRef.current = runCanvasKey;
    try {
      const started = await api.runWorkflowAsync(doc, "manual");
      setActiveRunId(started.executionId);
      const es = api.streamWorkflowRun(started.executionId);
      runEventSourceRef.current?.close();
      runEventSourceRef.current = es;
      const isCurrentRun = () => activeRunCanvasKeyRef.current === runCanvasKey;
      es.addEventListener("node.started", (ev) => {
        if (!isCurrentRun()) return;
        const data = JSON.parse((ev as MessageEvent).data) as { nodeId: string };
        setRunning(data.nodeId, true);
      });
      es.addEventListener("node.succeeded", (ev) => {
        if (!isCurrentRun()) return;
        const data = JSON.parse((ev as MessageEvent).data) as { nodeId: string; items: unknown[]; durationMs: number };
        applyResults([{ nodeId: data.nodeId, status: "success", items: data.items, error: null, durationMs: data.durationMs }]);
        setRunning(data.nodeId, false);
      });
      es.addEventListener("node.failed", (ev) => {
        if (!isCurrentRun()) return;
        const data = JSON.parse((ev as MessageEvent).data) as { nodeId: string; error: string; durationMs: number };
        applyResults([{ nodeId: data.nodeId, status: "error", items: [], error: data.error, durationMs: data.durationMs }]);
        setRunning(data.nodeId, false);
      });
      es.addEventListener("execution.result", (ev) => {
        if (!isCurrentRun()) return;
        const data = JSON.parse((ev as MessageEvent).data) as { status: string; nodes: Parameters<typeof applyResults>[0] };
        applyResults(data.nodes);
        setLastRunStatus(data.status);
      });
      es.addEventListener("execution.closed", () => {
        es.close();
        if (runEventSourceRef.current === es) runEventSourceRef.current = null;
        if (!isCurrentRun()) return;
        setRunningAll(false);
        setActiveRunId(null);
        setRunningIds(new Set());
        activeRunCanvasKeyRef.current = null;
        void refreshExecutions();
      });
      es.onerror = () => {
        es.close();
        if (runEventSourceRef.current === es) runEventSourceRef.current = null;
        if (!isCurrentRun()) return;
        setRunningAll(false);
        setActiveRunId(null);
        setRunningIds(new Set());
        activeRunCanvasKeyRef.current = null;
        setLastRunStatus("error");
      };
    } catch {
      setLastRunStatus("error");
      setRunningAll(false);
      setRunningIds(new Set());
      activeRunCanvasKeyRef.current = null;
    }
  }, [buildDoc, applyResults, setRunning, refreshExecutions]);

  const nodeApi = useMemo(
    () => ({
      updateNodeData,
      updateParams,
      runNode,
      openInspector: setInspectorId,
      runningIds,
      canvasId: current?.id,
      scope,
      slug,
    }),
    [updateNodeData, updateParams, runNode, runningIds, current?.id, scope, slug],
  );

  const onConnect = useCallback(
    (c: Connection) => {
      remember();
      setEdges((eds) => addEdge({ ...c, animated: true }, eds));
    },
    [setEdges, remember],
  );

  // ── Add a node from the catalog ───────────────────────────────────────────
  const addNode = useCallback(
    (t: WorkflowNodeType, position: { x: number; y: number }) => {
      remember();
      setNodes((nds) => [...nds, makeCanvasNode(t, position)]);
    },
    [setNodes, remember],
  );

  // ── Drag & drop from the node browser ─────────────────────────────────────
  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);
  const onDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault();
      if (e.dataTransfer.files.length) {
        const files = Array.from(e.dataTransfer.files);
        const pos = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
        if (scope === "project" && slug) {
          await api.uploadWorkspaceFiles(slug, files);
          const added = files.flatMap((file, i) => {
            const isMedia = /\.(png|jpe?g|gif|webp|svg|mp4|webm|mov|pdf)$/i.test(file.name);
            const t = nodeTypes.find((nt) => nt.type === (isMedia ? "display.media" : "io.file_source"));
            if (!t) return [];
            const params = isMedia
              ? { url: `/api/workspace/projects/${encodeURIComponent(slug)}/raw-file?path=${encodeURIComponent(file.name)}` }
              : { source: "project", slug, path: file.name, mode: "text" };
            return [makeCanvasNode(t, { x: pos.x + i * 32, y: pos.y + i * 32 }, params)];
          });
          remember();
          setNodes((nds) => nds.concat(added));
        } else {
          const uploaded = await api.uploadChatFiles(files);
          const added = uploaded.saved.flatMap((saved, i) => {
            const isMedia = /\.(png|jpe?g|gif|webp|svg|mp4|webm|mov|pdf)$/i.test(saved.filename);
            const t = nodeTypes.find((nt) => nt.type === (isMedia ? "display.media" : "io.file_source"));
            if (!t) return [];
            const params = isMedia
              ? { url: `/api/media?path=${encodeURIComponent(saved.absolute_path)}` }
              : { source: "files", path: saved.filename, mode: "text" };
            return [makeCanvasNode(t, { x: pos.x + i * 32, y: pos.y + i * 32 }, params)];
          });
          remember();
          setNodes((nds) => nds.concat(added));
        }
        return;
      }
      const raw = e.dataTransfer.getData(CANVAS_DND_MIME);
      if (!raw) return;
      const t = JSON.parse(raw) as WorkflowNodeType;
      addNode(t, rf.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
    },
    [rf, scope, slug, nodeTypes, addNode, setNodes, remember],
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

  const stopRun = useCallback(async () => {
    if (!activeRunId) return;
    try {
      await api.cancelWorkflowRun(activeRunId);
    } catch {
      /* ignore */
    }
    runEventSourceRef.current?.close();
    runEventSourceRef.current = null;
    activeRunCanvasKeyRef.current = null;
    setRunningIds(new Set());
    setRunningAll(false);
    setLastRunStatus("cancelling");
  }, [activeRunId]);

  const loadExecution = useCallback(
    async (id: string) => {
      try {
        const detail = await api.getWorkflowExecution(id);
        applyResults(detail.nodes);
        setLastRunStatus(detail.status);
      } catch {
        /* ignore */
      }
    },
    [applyResults],
  );

  const loadCanvas = useCallback(
    async (target: OpenCanvas) => {
      try {
        const targetKey = canvasIdentityKey(target.scope, target.slug, target.id);
        if (activeRunCanvasKeyRef.current && activeRunCanvasKeyRef.current !== targetKey) {
          runEventSourceRef.current?.close();
          runEventSourceRef.current = null;
          activeRunCanvasKeyRef.current = null;
          setRunningIds(new Set());
          setRunningAll(false);
          setActiveRunId(null);
        }
        const doc = await api.getCanvas(target.scope, target.id, target.slug);
        const loaded = fromCanvasDoc(doc);
        setNodes(loaded.nodes);
        setEdges(loaded.edges);
        requestAnimationFrame(() => rf.setViewport(loaded.viewport));
        setCurrent(target);
        setName(doc.name || target.id);
        setScope(target.scope);
        setSlug(target.slug);
        setLastRevision(doc.revision ?? null);
        setSaveState("idle");
        localStorage.setItem(LAST_KEY, JSON.stringify(target));
        setOpenOpen(false);
        setInspectorId(null);
      } catch {
        /* ignore */
      }
    },
    [rf, setNodes, setEdges],
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

  // Live-reload when the agent's `canvas` tool updates the open board.
  useEventBus((env) => {
    if (env.topic !== "canvas.updated") return;
    const cur = current;
    if (saveState === "conflict") return;
    if (cur && env.data?.id === cur.id && (env.data?.scope ?? "global") === cur.scope) {
      void loadCanvas(cur);
    }
  });

  // ── Save / autosave ───────────────────────────────────────────────────────
  const doSave = useCallback(async (force = false) => {
    if (scope === "project" && !slug) return;
    setSaveState("saving");
    const doc = buildDoc(force ? null : lastRevision);
    try {
      const saved = await api.saveCanvas(doc);
      await api.registerWorkflowTriggers(doc).catch(() => null);
      const target: OpenCanvas = { id: doc.id, name: doc.name, scope, slug: doc.slug };
      setCurrent(target);
      setLastRevision(saved.revision);
      localStorage.setItem(LAST_KEY, JSON.stringify(target));
      void refreshLists();
      setSaveState("saved");
      setTimeout(() => setSaveState("idle"), 1500);
    } catch (e) {
      if (e instanceof Error && e.message.startsWith("409")) {
        setSaveState("conflict");
        return;
      }
      setSaveState("idle");
    }
  }, [scope, slug, buildDoc, lastRevision, refreshLists]);

  useEffect(() => {
    if (!current) return;
    if (saveState === "conflict") return;
    const t = setTimeout(() => void doSave(), 1500);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges]);

  const newCanvas = useCallback(() => {
    setNodes([]);
    setEdges([]);
    setCurrent(null);
    setName("Untitled");
    setLastRevision(null);
    setSaveState("idle");
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

  const { duplicateSelection } = useCanvasShortcuts({ selectedIds, setNodes, setSelectedIds, remember, undo, redo });

  const inspectorNode = inspectorId ? nodes.find((n) => n.id === inspectorId) ?? null : null;
  const sortedSaved = useMemo(
    () => [...saved].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)),
    [saved],
  );

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
            disabled={runningAll || nodes.length === 0}
            className="flex h-7 items-center gap-1.5 rounded-sm bg-emerald-600 px-2.5 text-xs font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-50"
          >
            {runningAll ? <Loader2 className="h-3 w-3 animate-spin" /> : <Play className="h-3 w-3" />}
            Run
          </button>
          {activeRunId && (
            <button
              type="button"
              onClick={() => void stopRun()}
              className="flex h-7 items-center gap-1.5 rounded-sm bg-destructive px-2.5 text-xs font-semibold text-destructive-foreground transition hover:bg-destructive/90"
            >
              <Square className="h-3 w-3" /> Stop
            </button>
          )}
          {lastRunStatus && (
            <span className="rounded-sm border border-border px-2 py-1 text-[11px] text-muted-foreground">
              {lastRunStatus}
            </span>
          )}
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
            className={`flex h-7 items-center gap-1.5 rounded-sm border px-2.5 text-xs transition disabled:opacity-50 ${
              saveState === "conflict"
                ? "border-amber-500/60 bg-amber-500/10 text-amber-300"
                : "border-border text-muted-foreground hover:bg-secondary hover:text-foreground"
            }`}
          >
            {saveState === "saving" ? <Loader2 className="h-3 w-3 animate-spin" /> : saveState === "saved" ? <Check className="h-3 w-3" /> : <Save className="h-3 w-3" />}
            {saveState === "conflict" ? "Conflict" : "Save"}
          </button>
          {saveState === "conflict" && current && (
            <>
              <button
                type="button"
                onClick={() => void loadCanvas(current)}
                className="flex h-7 items-center gap-1.5 rounded-sm border border-amber-500/40 px-2.5 text-xs text-amber-300 transition hover:bg-amber-500/10"
              >
                Reload remote
              </button>
              <button
                type="button"
                onClick={() => void doSave(true)}
                className="flex h-7 items-center gap-1.5 rounded-sm border border-amber-500/40 px-2.5 text-xs text-amber-300 transition hover:bg-amber-500/10"
              >
                Save over
              </button>
            </>
          )}
          <button
            type="button"
            onClick={undo}
            disabled={!canUndo}
            title="Undo"
            className="grid h-7 w-7 place-items-center rounded-sm border border-border text-muted-foreground transition hover:bg-secondary hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
          >
            <Undo2 className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={redo}
            disabled={!canRedo}
            title="Redo"
            className="grid h-7 w-7 place-items-center rounded-sm border border-border text-muted-foreground transition hover:bg-secondary hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
          >
            <Redo2 className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={duplicateSelection}
            disabled={selectedIds.length === 0}
            title="Duplicate selection"
            className="grid h-7 w-7 place-items-center rounded-sm border border-border text-muted-foreground transition hover:bg-secondary hover:text-foreground disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
          >
            <Copy className="h-3.5 w-3.5" />
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
            onClick={() => {
              void refreshExecutions();
              setHistoryOpen((o) => !o);
            }}
            className="flex h-7 items-center gap-1.5 rounded-sm border border-border px-2.5 text-xs text-muted-foreground transition hover:bg-secondary hover:text-foreground"
          >
            <History className="h-3 w-3" /> History
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
            disabled={!current}
            className="ml-auto flex h-7 items-center gap-1.5 rounded-sm border border-border px-2.5 text-xs text-muted-foreground transition hover:bg-destructive/15 hover:text-destructive disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-muted-foreground"
          >
            <Trash2 className="h-3 w-3" /> Delete
          </button>
        </div>

        {/* Open browser */}
        {openOpen && (
          <div className="absolute right-3 top-12 z-20 max-h-80 w-72 overflow-y-auto rounded-md border border-border bg-popover p-1.5 shadow-2xl">
            {sortedSaved.length === 0 && <p className="px-2 py-3 text-center text-xs text-muted-foreground">No saved canvases.</p>}
            {sortedSaved.map((c) => (
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

        {historyOpen && (
          <div className="absolute right-3 top-12 z-20 max-h-96 w-80 overflow-y-auto rounded-md border border-border bg-popover p-1.5 shadow-2xl">
            {executions.length === 0 && <p className="px-2 py-3 text-center text-xs text-muted-foreground">No executions yet.</p>}
            {executions.map((ex) => (
            <button
              key={ex.id}
              type="button"
              onClick={() => void loadExecution(ex.id)}
                className="flex w-full flex-col gap-1 rounded-sm px-2 py-1.5 text-left text-xs text-foreground transition hover:bg-secondary"
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className="truncate font-mono text-[11px]">{ex.id}</span>
                  <span className={ex.status === "success" ? "text-emerald-400" : "text-destructive"}>{ex.status}</span>
                </span>
                <span className="text-[10px] text-muted-foreground">
                  {ex.trigger} · {new Date(ex.started_at * 1000).toLocaleString()}
                  {ex.finished_at ? ` · ${Math.max(0, Math.round(ex.finished_at - ex.started_at))}s` : ""}
                </span>
                {ex.error && <span className="line-clamp-2 text-[10px] text-destructive">{ex.error}</span>}
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
              onSelectionChange={({ nodes: selected }) => setSelectedIds(selected.map((n) => n.id))}
              onEdgeMouseEnter={((_event, edge) => {
                const source = nodes.find((n) => n.id === edge.source);
                const items = ((source?.data as CanvasNodeData | undefined)?.result?.items ?? []) as unknown[];
                setEdgePreview({ x: _event.clientX, y: _event.clientY, edge, items });
              }) as EdgeMouseHandler}
              onEdgeMouseLeave={() => setEdgePreview(null)}
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
          {nodes.length === 0 && (
            <button
              type="button"
              onClick={() => setBrowserOpen(true)}
              className="absolute left-1/2 top-1/2 z-10 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 rounded-sm border border-border bg-card/90 px-3 py-2 text-xs text-muted-foreground shadow-xl transition hover:bg-secondary hover:text-foreground"
            >
              <Plus className="h-3.5 w-3.5" />
              Add your first node
            </button>
          )}
          {edgePreview && (
            <div
              className="pointer-events-none fixed z-50 max-w-xs rounded-md border border-border bg-popover p-2 text-[10px] text-foreground shadow-xl"
              style={{ left: edgePreview.x + 12, top: edgePreview.y + 12 }}
            >
              <div className="mb-1 font-semibold text-muted-foreground">
                {edgePreview.edge.source} → {edgePreview.edge.target} · {edgePreview.items.length} item(s)
              </div>
              <pre className="max-h-32 overflow-hidden whitespace-pre-wrap font-mono">
                {JSON.stringify(edgePreview.items.slice(0, 2).map((i) => (i as { json?: unknown }).json ?? i), null, 2)}
              </pre>
            </div>
          )}
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
