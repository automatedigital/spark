import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ElementType } from "react";
import {
  AlertCircle,
  CheckCircle2,
  CircleDot,
  ClipboardList,
  PlayCircle,
  Search,
  Timer,
  UserRound,
  XCircle,
  Zap,
} from "lucide-react";
import {
  api,
  type KanbanBoardResponse,
  type KanbanTaskDetail,
  type KanbanTaskRow,
  sseUrl,
} from "@/lib/api";
import { useI18n } from "@/i18n";

const COLUMN_ORDER = ["triage", "todo", "ready", "running", "blocked", "done"] as const;
const STATUS_OPTIONS = ["triage", "todo", "ready", "running", "blocked", "done", "archived"] as const;
const TASK_TEMPLATES: Record<string, { title: string; body: string; priority: number }> = {
  bug: {
    title: "Fix: ",
    body: "Problem:\n\nExpected behavior:\n\nReproduction:\n\nAcceptance criteria:\n",
    priority: 2,
  },
  feature: {
    title: "Build: ",
    body: "Goal:\n\nScope:\n\nOut of scope:\n\nAcceptance criteria:\n",
    priority: 1,
  },
  research: {
    title: "Research: ",
    body: "Question:\n\nSources to inspect:\n\nOutput expected:\n",
    priority: 0,
  },
};

function colLabel(key: string): string {
  return key.charAt(0).toUpperCase() + key.slice(1);
}

const COLUMN_META: Record<string, { icon: ElementType; className: string }> = {
  triage: { icon: CircleDot, className: "text-slate-300 bg-slate-300/10" },
  todo: { icon: ClipboardList, className: "text-amber-200 bg-amber-300/12" },
  ready: { icon: Zap, className: "text-yellow-200 bg-yellow-300/12" },
  running: { icon: PlayCircle, className: "text-orange-200 bg-orange-300/12" },
  blocked: { icon: XCircle, className: "text-orange-200 bg-orange-300/12" },
  done: { icon: CheckCircle2, className: "text-lime-200 bg-lime-300/12" },
};

function formatTime(value?: number | null): string {
  if (!value) return "";
  return new Date(value * 1000).toLocaleString();
}

function eventPayload(raw?: string | null): string {
  if (!raw) return "";
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return Object.entries(parsed)
      .map(([k, v]) => `${k}: ${String(v)}`)
      .join(" · ");
  } catch {
    return raw;
  }
}

export default function KanbanPage() {
  const { t } = useI18n();
  const [boardSlug, setBoardSlug] = useState("default");
  const [search, setSearch] = useState("");
  const [tenant, setTenant] = useState("");
  const [assignee, setAssignee] = useState("");
  const [board, setBoard] = useState<KanbanBoardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KanbanTaskDetail | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [newAssignee, setNewAssignee] = useState("");
  const [newTenant, setNewTenant] = useState("");
  const [newPriority, setNewPriority] = useState(0);
  const [newBody, setNewBody] = useState("");
  const [templateKey, setTemplateKey] = useState("");
  const [commentBody, setCommentBody] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkStatus, setBulkStatus] = useState("todo");
  const [dispatchPreview, setDispatchPreview] = useState<string[] | null>(null);
  const [dispatchBlocked, setDispatchBlocked] = useState<string[]>([]);
  const [completeSummary, setCompleteSummary] = useState("");
  const [blockReason, setBlockReason] = useState("");
  const [linkParentId, setLinkParentId] = useState("");
  const [linkChildId, setLinkChildId] = useState("");

  const loadBoard = useCallback(async () => {
    setErr(null);
    try {
      const b = await api.getKanbanBoard({
        board: boardSlug,
        tenant: tenant || null,
        assignee: assignee || null,
        q: search || null,
      });
      setBoard(b);
      setDispatchPreview(null);
      setDispatchBlocked([]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [boardSlug, tenant, assignee, search]);

  const loadBoardRef = useRef(loadBoard);
  const selectedIdRef = useRef(selectedId);
  useEffect(() => {
    loadBoardRef.current = loadBoard;
  }, [loadBoard]);
  useEffect(() => {
    selectedIdRef.current = selectedId;
  }, [selectedId]);

  useEffect(() => {
    void loadBoard();
  }, [loadBoard]);

  useEffect(() => {
    const url = sseUrl("/api/kanban/events?since=0");
    const es = new EventSource(url);
    es.onmessage = () => {
      void loadBoardRef.current();
      const sid = selectedIdRef.current;
      if (sid) {
        api.getKanbanTask(sid).then(setDetail).catch(() => {});
      }
    };
    es.onerror = () => {
      es.close();
    };
    return () => es.close();
  }, []);

  const openTask = async (id: string) => {
    setSelectedId(id);
    try {
      const d = await api.getKanbanTask(id);
      setDetail(d);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const onDragStart = (e: React.DragEvent, taskId: string) => {
    e.dataTransfer.setData("text/task-id", taskId);
    e.dataTransfer.effectAllowed = "move";
  };

  const onDropColumn = async (e: React.DragEvent, status: string) => {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/task-id");
    if (!id) return;
    try {
      await api.patchKanbanTask(id, { status });
      void loadBoard();
      if (selectedId === id) void openTask(id);
    } catch (err2) {
      setErr(err2 instanceof Error ? err2.message : String(err2));
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const n = new Set(prev);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  };

  const runBulk = async () => {
    if (selectedIds.size === 0) return;
    try {
      const result = await api.bulkPatchKanbanTasks(Array.from(selectedIds), { status: bulkStatus });
      if (!result.ok) {
        setErr(
          Object.entries(result.errors)
            .map(([id, msg]) => `${id}: ${msg}`)
            .join("; "),
        );
      }
      setSelectedIds(new Set());
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const createTask = async () => {
    if (!newTitle.trim()) return;
    try {
      await api.createKanbanTask({
        title: newTitle.trim(),
        board: boardSlug,
        body: newBody,
        assignee: newAssignee.trim() || null,
        tenant: newTenant.trim() || null,
        priority: newPriority,
      });
      setNewTitle("");
      setNewAssignee("");
      setNewTenant("");
      setNewPriority(0);
      setNewBody("");
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const applyTemplate = (key: string) => {
    setTemplateKey(key);
    const template = TASK_TEMPLATES[key];
    if (!template) return;
    if (!newTitle.trim()) setNewTitle(template.title);
    if (!newBody.trim()) setNewBody(template.body);
    setNewPriority(template.priority);
  };

  const duplicateSelectedTask = async () => {
    if (!detail) return;
    try {
      await api.createKanbanTask({
        title: `Copy of ${detail.title}`,
        board: detail.board_slug ?? boardSlug,
        body: detail.body ?? "",
        assignee: detail.assignee,
        tenant: detail.tenant,
        priority: detail.priority ?? 0,
      });
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const retrySelectedTask = async () => {
    if (!selectedId) return;
    try {
      await api.patchKanbanTask(selectedId, { status: "ready" });
      await api.addKanbanComment(selectedId, "Retry requested from dashboard.", "web");
      await openTask(selectedId);
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const postComment = async () => {
    if (!selectedId || !commentBody.trim()) return;
    try {
      await api.addKanbanComment(selectedId, commentBody.trim());
      setCommentBody("");
      void openTask(selectedId);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const nudgeDispatch = async () => {
    try {
      const result = await api.dispatchKanban(3, dispatchPreview === null);
      if (result.dry_run) {
        setDispatchPreview(result.ready ?? []);
        setDispatchBlocked(result.blocked_by_assignee ?? []);
        return;
      }
      setDispatchPreview(null);
      setDispatchBlocked([]);
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const patchSelectedTask = async (patch: Parameters<typeof api.patchKanbanTask>[1]) => {
    if (!selectedId) return;
    try {
      await api.patchKanbanTask(selectedId, patch);
      await openTask(selectedId);
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const completeSelectedTask = async () => {
    if (!selectedId) return;
    try {
      await api.completeKanbanTask(selectedId, completeSummary.trim() || "Completed from dashboard");
      setCompleteSummary("");
      await openTask(selectedId);
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const blockSelectedTask = async () => {
    if (!selectedId || !blockReason.trim()) return;
    try {
      await api.blockKanbanTask(selectedId, blockReason.trim());
      setBlockReason("");
      await openTask(selectedId);
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const unblockSelectedTask = async () => {
    if (!selectedId) return;
    try {
      await api.unblockKanbanTask(selectedId);
      await openTask(selectedId);
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const addLink = async () => {
    if (!linkParentId.trim() || !linkChildId.trim()) return;
    try {
      await api.addKanbanLink(linkParentId.trim(), linkChildId.trim());
      setLinkParentId("");
      setLinkChildId("");
      if (selectedId) await openTask(selectedId);
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const columnTasks = useMemo(() => {
    if (!board) return {} as Record<string, KanbanTaskRow[]>;
    return board.columns;
  }, [board]);
  const totalTasks = useMemo(
    () => COLUMN_ORDER.reduce((sum, col) => sum + (columnTasks[col]?.length ?? 0), 0),
    [columnTasks],
  );

  return (
    <div className="flex flex-col gap-5 min-h-[60vh]">
      <header className="overflow-hidden rounded-sm border border-border bg-card/92 shadow-2xl shadow-black/20">
        <div className="grid gap-4 border-b border-border bg-[linear-gradient(135deg,rgba(255,163,43,0.16),rgba(255,214,142,0.06)_48%,rgba(15,23,26,0.82))] p-5 lg:grid-cols-[1fr_auto]">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-primary">
              <ClipboardList className="h-4 w-4" />
              Task Board
            </div>
            <h1 className="text-2xl font-semibold tracking-normal text-foreground sm:text-3xl">
              Coordinate work across Spark profiles.
            </h1>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
              <span className="rounded-full border border-border bg-background/55 px-3 py-1">
                Board: {boardSlug || "default"}
              </span>
              <span className="rounded-full border border-border bg-background/55 px-3 py-1">
                {totalTasks} visible tasks
              </span>
              {board?.assignees?.length ? (
                <span className="rounded-full border border-border bg-background/55 px-3 py-1">
                  {board.assignees.length} assignees
                </span>
              ) : null}
            </div>
          </div>
          <div className="flex flex-wrap gap-2 items-center">
            <button
              type="button"
              className="px-3 py-2 text-xs font-semibold border border-border bg-background/70 hover:bg-secondary"
              onClick={() => void loadBoard()}
            >
              {t.common.refresh}
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-2 bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground shadow-sm hover:bg-primary/90"
              onClick={() => void nudgeDispatch()}
            >
              <Zap className="h-4 w-4" />
              {dispatchPreview === null ? "Preview dispatch" : "Confirm dispatch"}
            </button>
          </div>
        </div>
        {dispatchPreview !== null && (
          <div className="m-4 rounded-sm border border-primary/25 bg-primary/10 p-3 text-xs">
            <div className="font-semibold text-primary">
              Ready to dispatch: {dispatchPreview.length ? dispatchPreview.join(", ") : "none"}
            </div>
            {dispatchBlocked.length > 0 && (
              <div className="mt-1 opacity-70">Skipped active assignees: {dispatchBlocked.join(", ")}</div>
            )}
            <button
              type="button"
              className="mt-2 opacity-70 underline"
              onClick={() => {
                setDispatchPreview(null);
                setDispatchBlocked([]);
              }}
            >
              Cancel
            </button>
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 p-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Board</span>
            <input
              className="border border-border bg-background px-3 py-2 shadow-inner"
              value={boardSlug}
              onChange={(e) => setBoardSlug(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">{t.common.search}</span>
            <span className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <input
                className="w-full border border-border bg-background py-2 pl-9 pr-3 shadow-inner"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Title, body, id"
              />
            </span>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Tenant</span>
            <select
              className="border border-border bg-background px-3 py-2 shadow-inner"
              value={tenant}
              onChange={(e) => setTenant(e.target.value)}
            >
              <option value="">—</option>
              {(board?.tenants ?? []).map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">Assignee</span>
            <select
              className="border border-border bg-background px-3 py-2 shadow-inner"
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
            >
              <option value="">—</option>
              {(board?.assignees ?? []).map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </label>
        </div>
        {selectedIds.size > 0 && (
          <div className="mx-4 mb-4 flex flex-wrap gap-2 items-center rounded-sm border border-border bg-secondary/60 p-3 text-sm">
            <span>{selectedIds.size} selected</span>
            <select
              className="border border-border bg-background px-2 py-1.5"
              value={bulkStatus}
              onChange={(e) => setBulkStatus(e.target.value)}
            >
              {COLUMN_ORDER.map((c) => (
                <option key={c} value={c}>
                  {colLabel(c)}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="px-2 py-1 border border-border"
              onClick={() => void runBulk()}
            >
              Apply
            </button>
            <button type="button" className="px-2 py-1 opacity-70" onClick={() => setSelectedIds(new Set())}>
              Clear
            </button>
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 border-t border-border bg-background/32 p-4 md:grid-cols-2 xl:grid-cols-5">
          <select
            className="border border-border bg-background px-3 py-2 shadow-inner"
            value={templateKey}
            onChange={(e) => applyTemplate(e.target.value)}
          >
            <option value="">Template</option>
            <option value="bug">Bug</option>
            <option value="feature">Feature</option>
            <option value="research">Research</option>
          </select>
          <input
            className="border border-border bg-background px-3 py-2 shadow-inner"
            placeholder="New task title"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <input
            className="border border-border bg-background px-3 py-2 shadow-inner"
            placeholder="Assignee (worker label)"
            value={newAssignee}
            onChange={(e) => setNewAssignee(e.target.value)}
          />
          <input
            className="border border-border bg-background px-3 py-2 shadow-inner"
            placeholder="Tenant"
            value={newTenant}
            onChange={(e) => setNewTenant(e.target.value)}
          />
          <input
            className="border border-border bg-background px-3 py-2 shadow-inner"
            type="number"
            placeholder="Priority"
            value={newPriority}
            onChange={(e) => setNewPriority(Number(e.target.value) || 0)}
          />
          <button
            type="button"
            className="border border-primary/25 bg-primary/10 px-3 py-2 font-semibold text-primary hover:bg-primary/15"
            onClick={() => void createTask()}
          >
            {t.common.create} task
          </button>
        </div>
        <textarea
          className="mx-4 mb-4 min-h-[64px] w-[calc(100%-2rem)] border border-border bg-background px-3 py-2 text-sm shadow-inner"
          placeholder="Description (optional)"
          value={newBody}
          onChange={(e) => setNewBody(e.target.value)}
        />
      </header>

      {loading && <p className="text-sm opacity-70">{t.common.loading}</p>}
      {err && (
        <div className="flex items-start gap-2 rounded-sm border border-destructive/25 bg-destructive/10 p-3 text-sm text-destructive" role="alert">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{err.includes("401") ? "Dashboard token is missing or invalid. Reload and enter the token from dashboard.token." : err}</span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 items-start md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        {COLUMN_ORDER.map((col) => {
          const Icon = COLUMN_META[col].icon;
          return (
          <section
            key={col}
            className="flex min-h-[320px] flex-col overflow-hidden rounded-sm border border-border bg-card/88 shadow-xl shadow-black/14"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => void onDropColumn(e, col)}
          >
            <div className="flex items-center justify-between border-b border-border px-3 py-3">
              <div className="flex items-center gap-2">
                <span className={`grid h-7 w-7 place-items-center rounded-sm ${COLUMN_META[col].className}`}>
                  <Icon className="h-4 w-4" />
                </span>
                <span className="text-xs font-semibold uppercase tracking-[0.08em] text-foreground">
                  {colLabel(col)}
                </span>
              </div>
              <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
                {columnTasks[col]?.length ?? 0}
              </span>
            </div>
            <div className="flex flex-col gap-2 p-2 overflow-y-auto max-h-[62vh]">
              {(columnTasks[col] ?? []).map((task) => (
                <div
                  key={task.id}
                  draggable
                  onDragStart={(e) => onDragStart(e, task.id)}
                  className={`rounded-sm border px-3 py-3 cursor-grab active:cursor-grabbing text-sm shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
                    selectedId === task.id ? "border-primary ring-2 ring-primary/15" : "border-border"
                  } bg-background/90`}
                  onClick={() => void openTask(task.id)}
                >
                  <div className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(task.id)}
                      onChange={(e) => {
                        e.stopPropagation();
                        toggleSelect(task.id);
                      }}
                      className="mt-1"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium truncate">{task.title}</div>
                      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <span>{task.id}</span>
                        <span className="inline-flex items-center gap-1">
                          <UserRound className="h-3 w-3" />
                          {String(task.assignee ?? "unassigned")}
                        </span>
                        {task.priority ? (
                          <span className="inline-flex items-center gap-1">
                            <Timer className="h-3 w-3" />
                            P{String(task.priority)}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )})}
      </div>

      {detail && (
        <aside className="fixed inset-y-0 right-0 w-full sm:w-[460px] border-l border-border bg-card shadow-2xl z-50 flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border bg-background/70">
            <h2 className="font-display text-sm uppercase tracking-wider truncate pr-2">{detail.title}</h2>
            <button
              type="button"
              className="text-xs uppercase tracking-wider opacity-70"
              onClick={() => {
                setSelectedId(null);
                setDetail(null);
              }}
            >
              {t.common.close}
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-4 text-sm space-y-4">
            <div className="opacity-80 text-xs">
              <div>ID: {detail.id}</div>
              <div>Status: {detail.status}</div>
              <div>Assignee: {String(detail.assignee ?? "—")}</div>
              <div>Priority: {String(detail.priority ?? 0)}</div>
              <div>Tenant: {String(detail.tenant ?? "—")}</div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <label className="flex flex-col gap-1">
                <span className="uppercase tracking-wider opacity-70">Status</span>
                <select
                  className="border border-border bg-background px-2 py-1"
                  value={detail.status}
                  onChange={(e) => void patchSelectedTask({ status: e.target.value })}
                >
                  {STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>
                      {colLabel(status)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="uppercase tracking-wider opacity-70">Priority</span>
                <input
                  key={`priority-${detail.id}-${detail.priority ?? 0}`}
                  className="border border-border bg-background px-2 py-1"
                  type="number"
                  defaultValue={Number(detail.priority ?? 0)}
                  onBlur={(e) => void patchSelectedTask({ priority: Number(e.target.value) || 0 })}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="uppercase tracking-wider opacity-70">Assignee</span>
                <input
                  key={`assignee-${detail.id}-${detail.assignee ?? ""}`}
                  className="border border-border bg-background px-2 py-1"
                  defaultValue={String(detail.assignee ?? "")}
                  onBlur={(e) => void patchSelectedTask({ assignee: e.target.value })}
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="uppercase tracking-wider opacity-70">Tenant</span>
                <input
                  key={`tenant-${detail.id}-${detail.tenant ?? ""}`}
                  className="border border-border bg-background px-2 py-1"
                  defaultValue={String(detail.tenant ?? "")}
                  onBlur={(e) => void patchSelectedTask({ tenant: e.target.value })}
                />
              </label>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <button
                type="button"
                className="px-2 py-1 border border-border"
                onClick={() => void patchSelectedTask({ status: "archived" })}
              >
                Archive
              </button>
              <button type="button" className="px-2 py-1 border border-border" onClick={() => void unblockSelectedTask()}>
                Unblock
              </button>
              <button type="button" className="px-2 py-1 border border-border" onClick={() => void retrySelectedTask()}>
                Retry
              </button>
              <button type="button" className="px-2 py-1 border border-border" onClick={() => void duplicateSelectedTask()}>
                Duplicate
              </button>
            </div>
            <div className="grid grid-cols-1 gap-2 text-xs">
              <div className="flex gap-2">
                <input
                  className="flex-1 border border-border bg-background px-2 py-1"
                  value={completeSummary}
                  onChange={(e) => setCompleteSummary(e.target.value)}
                  placeholder="Completion summary"
                />
                <button
                  type="button"
                  className="px-2 py-1 border border-border"
                  onClick={() => void completeSelectedTask()}
                >
                  Complete
                </button>
              </div>
              <div className="flex gap-2">
                <input
                  className="flex-1 border border-border bg-background px-2 py-1"
                  value={blockReason}
                  onChange={(e) => setBlockReason(e.target.value)}
                  placeholder="Block reason"
                />
                <button type="button" className="px-2 py-1 border border-border" onClick={() => void blockSelectedTask()}>
                  Block
                </button>
              </div>
            </div>
            <pre className="whitespace-pre-wrap opacity-90 text-xs border border-border p-2 max-h-40 overflow-y-auto">
              {detail.body || "(no description)"}
            </pre>
            <div>
              <div className="text-xs uppercase tracking-wider mb-2 opacity-70">Link Tasks</div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
                <input
                  className="border border-border bg-background px-2 py-1"
                  value={linkParentId}
                  onChange={(e) => setLinkParentId(e.target.value)}
                  placeholder="Parent id"
                />
                <input
                  className="border border-border bg-background px-2 py-1"
                  value={linkChildId}
                  onChange={(e) => setLinkChildId(e.target.value)}
                  placeholder="Child id"
                />
                <button type="button" className="px-2 py-1 border border-border" onClick={() => void addLink()}>
                  Link
                </button>
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider mb-1 opacity-70">Parents</div>
              <ul className="text-xs space-y-1">
                {detail.parents?.length ? (
                  detail.parents.map((p) => (
                    <li key={p}>
                      <button type="button" className="underline" onClick={() => void openTask(p)}>
                        {p}
                      </button>
                    </li>
                  ))
                ) : (
                  <li>—</li>
                )}
              </ul>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider mb-1 opacity-70">Children</div>
              <ul className="text-xs space-y-1">
                {detail.children?.length ? (
                  detail.children.map((c) => (
                    <li key={c}>
                      <button type="button" className="underline" onClick={() => void openTask(c)}>
                        {c}
                      </button>
                    </li>
                  ))
                ) : (
                  <li>—</li>
                )}
              </ul>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider mb-2 opacity-70">Comments</div>
              <ul className="space-y-2 text-xs max-h-36 overflow-y-auto">
                {(detail.comments ?? []).map((c) => (
                  <li key={c.id} className="border border-border p-2">
                    <span className="opacity-60">{c.author ?? "?"}</span>: {c.body}
                  </li>
                ))}
              </ul>
              <div className="flex gap-2 mt-2">
                <input
                  className="flex-1 border border-border px-2 py-1"
                  value={commentBody}
                  onChange={(e) => setCommentBody(e.target.value)}
                  placeholder="Add comment"
                />
                <button type="button" className="px-2 py-1 border border-border" onClick={() => void postComment()}>
                  Send
                </button>
              </div>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider mb-1 opacity-70">Runs</div>
              <ul className="text-xs space-y-2 max-h-36 overflow-y-auto opacity-90">
                {(detail.runs ?? []).map((r) => (
                  <li key={r.id} className="border border-border p-2">
                    <div className="font-medium">{r.outcome}</div>
                    <div className="opacity-60">
                      {r.profile || "worker"} · {formatTime(r.started_at)}
                    </div>
                    {(r.summary || r.error) && <div className="mt-1">{r.summary || r.error}</div>}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="text-xs uppercase tracking-wider mb-1 opacity-70">Events</div>
              <ul className="text-xs space-y-2 max-h-36 overflow-y-auto opacity-90">
                {(detail.events ?? []).map((event) => (
                  <li key={event.id} className="border border-border p-2">
                    <div className="font-medium">{event.kind}</div>
                    <div className="opacity-60">{formatTime(event.created_at)}</div>
                    {eventPayload(event.payload_json) && <div className="mt-1">{eventPayload(event.payload_json)}</div>}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}
