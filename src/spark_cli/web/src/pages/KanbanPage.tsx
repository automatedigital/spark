import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ElementType } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ClipboardList,
  Eye,
  Paperclip,
  PlayCircle,
  Send,
  Sparkles,
  Trash2,
  UserRound,
} from "lucide-react";
import { timeAgo } from "@/lib/utils";
import {
  api,
  type KanbanBoardResponse,
  type KanbanTaskDetail,
  type KanbanTaskRow,
  type WorkspaceProject,
  sseUrl,
} from "@/lib/api";
import { Toast } from "@/components/Toast";
import { useI18n } from "@/i18n";
import { useToast } from "@/hooks/useToast";
import { GLOBAL_NAV_EVENT, takeGlobalNavTarget, type GlobalNavTarget } from "@/lib/globalNavigation";

const DEFAULT_BOARD = "default";
const COLUMN_ORDER = ["todo", "ready", "running", "user_review", "done"] as const;
const STATUS_OPTIONS = ["todo", "ready", "running", "user_review", "done", "blocked", "archived"] as const;
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

const STATUS_LABELS: Record<string, string> = {
  todo: "Planned",
  ready: "Send to Spark",
  running: "In-Progress",
  user_review: "User Review",
  done: "Complete",
  blocked: "Blocked",
  archived: "Archived",
};

const COLUMN_META: Record<string, { icon: ElementType; className: string }> = {
  todo: { icon: ClipboardList, className: "text-amber-200 bg-amber-300/12" },
  ready: { icon: Send, className: "text-yellow-200 bg-yellow-300/12" },
  running: { icon: PlayCircle, className: "text-orange-200 bg-orange-300/12" },
  user_review: { icon: Eye, className: "text-sky-200 bg-sky-300/12" },
  done: { icon: CheckCircle2, className: "text-lime-200 bg-lime-300/12" },
};

function colLabel(key: string): string {
  return STATUS_LABELS[key] ?? key.charAt(0).toUpperCase() + key.slice(1);
}

function PriorityDot({ priority }: { priority?: number }) {
  if (priority === undefined || priority === null) return null;
  const cls =
    priority === 0 ? "bg-muted-foreground/40"
    : priority === 1 ? "bg-blue-400"
    : priority === 2 ? "bg-amber-400"
    : "bg-red-500";
  const title =
    priority === 0 ? "No priority"
    : priority === 1 ? "Low"
    : priority === 2 ? "High"
    : "Urgent";
  return <span className={`h-2 w-2 rounded-full shrink-0 ${cls}`} title={title} />;
}

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

function eventReachedUserReview(raw: string): string | null {
  try {
    const event = JSON.parse(raw) as {
      task_id?: string;
      kind?: string;
      payload_json?: string | null;
    };
    const payload = event.payload_json ? (JSON.parse(event.payload_json) as Record<string, unknown>) : {};
    if (
      event.kind === "completed" ||
      (event.kind === "status" && payload.to === "user_review")
    ) {
      return event.task_id ?? null;
    }
  } catch {
    return null;
  }
  return null;
}

export default function KanbanPage() {
  const { t } = useI18n();
  const { toast, showToast } = useToast(5000);
  const [search] = useState("");
  const [tenant] = useState("");
  const [assignee] = useState("");
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
  const [completeSummary, setCompleteSummary] = useState("");
  const [linkParentId, setLinkParentId] = useState("");
  const [linkChildId, setLinkChildId] = useState("");
  const [workspaceProjects, setWorkspaceProjects] = useState<WorkspaceProject[]>([]);
  const [newWorkspaceSlug, setNewWorkspaceSlug] = useState("");
  const [uploadingTask, setUploadingTask] = useState(false);
  const [uploadingNew, setUploadingNew] = useState(false);
  const taskFileInputRef = useRef<HTMLInputElement>(null);
  const newFileInputRef = useRef<HTMLInputElement>(null);

  const loadBoard = useCallback(async () => {
    setErr(null);
    try {
      const b = await api.getKanbanBoard({
        board: DEFAULT_BOARD,
        tenant: tenant || null,
        assignee: assignee || null,
        q: search || null,
      });
      setBoard(b);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [tenant, assignee, search]);

  const loadBoardRef = useRef(loadBoard);
  const selectedIdRef = useRef(selectedId);
  const notifiedReviewIdsRef = useRef<Set<string>>(new Set());
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
    es.onmessage = (event) => {
      const reviewTaskId = eventReachedUserReview(event.data);
      void loadBoardRef.current();
      const sid = selectedIdRef.current;
      if (sid) {
        api.getKanbanTask(sid).then(setDetail).catch(() => {});
      }
      if (reviewTaskId && !notifiedReviewIdsRef.current.has(reviewTaskId)) {
        notifiedReviewIdsRef.current.add(reviewTaskId);
        api.getKanbanTask(reviewTaskId)
          .then((task) => {
            const message = `Task ready for review: ${task.title}`;
            showToast(message, "success");
            if ("Notification" in window && Notification.permission === "granted") {
              new Notification("Spark task ready for review", { body: task.title });
            }
          })
          .catch(() => showToast("Task ready for review", "success"));
      }
    };
    es.onerror = () => {
      es.close();
    };
    return () => es.close();
  }, [showToast]);

  useEffect(() => {
    api.listWorkspaceProjects()
      .then((res) => setWorkspaceProjects(res.projects))
      .catch(() => {});
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

  useEffect(() => {
    const taskTarget = takeGlobalNavTarget("task");
    if (taskTarget) void openTask(taskTarget.id);

    const handler = (event: Event) => {
      const target = (event as CustomEvent<GlobalNavTarget>).detail;
      if (target?.type === "task") void openTask(target.id);
    };
    window.addEventListener(GLOBAL_NAV_EVENT, handler);
    return () => window.removeEventListener(GLOBAL_NAV_EVENT, handler);
  }, []);

  const onDragStart = (e: React.DragEvent, taskId: string) => {
    e.dataTransfer.setData("text/task-id", taskId);
    e.dataTransfer.effectAllowed = "move";
  };

  const moveTask = async (id: string, status: string) => {
    if (status === "done") {
      await api.patchKanbanTask(id, { status: "done" });
    } else {
      await api.patchKanbanTask(id, { status });
    }
    if (status === "ready") {
      await api.dispatchKanban(3, false);
    }
  };

  const onDropColumn = async (e: React.DragEvent, status: string) => {
    e.preventDefault();
    const id = e.dataTransfer.getData("text/task-id");
    if (!id) return;
    try {
      await moveTask(id, status);
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
      const ids = Array.from(selectedIds);
      const result = await api.bulkPatchKanbanTasks(ids, { status: bulkStatus });
      if (!result.ok) {
        setErr(
          Object.entries(result.errors)
            .map(([id, msg]) => `${id}: ${msg}`)
            .join("; "),
        );
      }
      if (bulkStatus === "ready") {
        await api.dispatchKanban(3, false);
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
      const selectedProject = workspaceProjects.find((p) => p.slug === newWorkspaceSlug);
      await api.createKanbanTask({
        title: newTitle.trim(),
        board: DEFAULT_BOARD,
        body: newBody,
        assignee: newAssignee.trim() || null,
        tenant: newTenant.trim() || null,
        priority: newPriority,
        workspace_path: selectedProject?.path ?? null,
      });
      setNewTitle("");
      setNewAssignee("");
      setNewTenant("");
      setNewPriority(0);
      setNewBody("");
      setNewWorkspaceSlug("");
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
        board: DEFAULT_BOARD,
        body: detail.body ?? "",
        assignee: detail.assignee,
        tenant: detail.tenant,
        priority: detail.priority ?? 0,
        workspace_path: detail.workspace_path ?? null,
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
      await api.addKanbanComment(selectedId, "Sent back to Spark from dashboard.", "web");
      await api.dispatchKanban(3, false);
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
      if (completeSummary.trim()) {
        await api.addKanbanComment(selectedId, completeSummary.trim(), "user");
      }
      await api.patchKanbanTask(selectedId, { status: "done" });
      setCompleteSummary("");
      await openTask(selectedId);
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const deleteSelectedTask = async () => {
    if (!selectedId || !detail) return;
    if (!confirm(`Delete task "${detail.title}"? This cannot be undone.`)) return;
    try {
      await api.deleteKanbanTask(selectedId);
      setSelectedId(null);
      setDetail(null);
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(selectedId);
        return next;
      });
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const uploadFilesForPath = async (files: File[], workspacePath: string | null) => {
    const project = workspaceProjects.find((p) => p.path === workspacePath);
    if (project) {
      const res = await api.uploadWorkspaceFiles(project.slug, files, "files");
      return { count: res.saved.length, where: `workspace/${project.slug}/files` };
    }
    const res = await api.uploadChatFiles(files);
    return { count: res.saved.length, where: `workspace/files` };
  };

  const onUploadToTask = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length || !detail) return;
    setUploadingTask(true);
    try {
      const { count, where } = await uploadFilesForPath(files, detail.workspace_path ?? null);
      showToast(`Uploaded ${count} file${count === 1 ? "" : "s"} to ${where}/`, "success");
    } catch (err2) {
      setErr(err2 instanceof Error ? err2.message : String(err2));
    } finally {
      setUploadingTask(false);
    }
  };

  const onUploadForNewTask = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = "";
    if (!files.length) return;
    setUploadingNew(true);
    try {
      const project = workspaceProjects.find((p) => p.slug === newWorkspaceSlug);
      const { count, where } = await uploadFilesForPath(files, project?.path ?? null);
      showToast(`Uploaded ${count} file${count === 1 ? "" : "s"} to ${where}/`, "success");
    } catch (err2) {
      setErr(err2 instanceof Error ? err2.message : String(err2));
    } finally {
      setUploadingNew(false);
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
      <Toast toast={toast} />
      <header className="overflow-hidden rounded-sm border border-border bg-card/92 shadow-2xl shadow-black/20">
        <div className="grid gap-4 border-b border-border bg-[linear-gradient(135deg,rgba(255,163,43,0.16),rgba(255,214,142,0.06)_48%,rgba(15,23,26,0.82))] p-5 lg:grid-cols-[1fr_auto]">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-primary">
              <ClipboardList className="h-4 w-4" />
              Tasks
            </div>
            <h1 className="text-2xl font-semibold tracking-normal text-foreground sm:text-3xl">
              Plan work, send it to Spark, review the result.
            </h1>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
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
          </div>
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
          <input
            className="border border-border bg-background px-3 py-2 shadow-inner"
            placeholder="Task title"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
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
          <select
            className="border border-border bg-background px-3 py-2 shadow-inner"
            value={newWorkspaceSlug}
            onChange={(e) => setNewWorkspaceSlug(e.target.value)}
          >
            <option value="">Project (optional)</option>
            {workspaceProjects.map((p) => (
              <option key={p.slug} value={p.slug}>{p.name}</option>
            ))}
          </select>
          <input
            className="border border-border bg-background px-3 py-2 shadow-inner"
            placeholder="Worker label"
            value={newAssignee}
            onChange={(e) => setNewAssignee(e.target.value)}
          />
          <input
            ref={newFileInputRef}
            type="file"
            multiple
            className="hidden"
            onChange={(e) => void onUploadForNewTask(e)}
          />
          <button
            type="button"
            disabled={uploadingNew}
            className="border border-border bg-secondary px-3 py-2 font-semibold text-foreground hover:bg-secondary/80 disabled:opacity-60 inline-flex items-center justify-center gap-2"
            onClick={() => newFileInputRef.current?.click()}
          >
            <Paperclip className="h-4 w-4" />
            {uploadingNew ? "Uploading…" : "Attach files"}
          </button>
          <button
            type="button"
            className="border border-primary/25 bg-primary/10 px-3 py-2 font-semibold text-primary hover:bg-primary/15"
            onClick={() => void createTask()}
          >
            {t.common.create} task
          </button>
        </div>
        <textarea
          className="mx-4 mb-4 min-h-[84px] w-[calc(100%-2rem)] border border-border bg-background px-3 py-2 text-sm shadow-inner"
          placeholder="Task brief, constraints, acceptance criteria, useful context"
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

      <div className="grid grid-cols-1 gap-4 items-start md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
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
                    className={`rounded-sm border px-3 py-2.5 cursor-grab active:cursor-grabbing text-sm shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
                      selectedId === task.id ? "border-primary ring-2 ring-primary/15" : "border-border"
                    } bg-background/90`}
                    onClick={() => void openTask(task.id)}
                  >
                    {/* Title row + priority dot */}
                    <div className="flex items-start gap-2">
                      <input
                        type="checkbox"
                        checked={selectedIds.has(task.id)}
                        onChange={(e) => {
                          e.stopPropagation();
                          toggleSelect(task.id);
                        }}
                        className="mt-1 shrink-0"
                      />
                      <div className="flex-1 min-w-0 flex items-start justify-between gap-1">
                        <div className="font-medium truncate leading-snug">{task.title}</div>
                        <PriorityDot priority={task.priority} />
                      </div>
                    </div>
                    {/* Body preview */}
                    {task.body && (
                      <p className="mt-1.5 ml-6 text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                        {task.body.slice(0, 120)}
                        {task.body.length > 120 ? "…" : ""}
                      </p>
                    )}
                    {/* Meta row */}
                    <div className="mt-2 ml-6 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                      {task.assignee ? (
                        <span className="inline-flex items-center gap-1 rounded-full border border-border bg-secondary/60 px-2 py-0.5 font-medium">
                          <UserRound className="h-3 w-3" />
                          {task.assignee}
                        </span>
                      ) : (
                        <span />
                      )}
                      {task.updated_at ? (
                        <span className="shrink-0 opacity-60">{timeAgo(task.updated_at)}</span>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          );
        })}
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
              <div>Status: {colLabel(detail.status)}</div>
              <div>Worker: {String(detail.assignee ?? "—")}</div>
              <div>Priority: {String(detail.priority ?? 0)}</div>
              <div>Tenant: {String(detail.tenant ?? "—")}</div>
              {!!detail.workspace_path && (
                <div>
                  Project:{" "}
                  {String(workspaceProjects.find((p) => p.path === detail.workspace_path)?.name ??
                    detail.workspace_path)}
                </div>
              )}
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
                <span className="uppercase tracking-wider opacity-70">Worker</span>
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
              <label className="flex flex-col col-span-2 gap-1">
                <span className="uppercase tracking-wider opacity-70">Workspace Project</span>
                <select
                  key={`workspace-${detail.id}-${String(detail.workspace_path ?? "")}`}
                  className="border border-border bg-background px-2 py-1"
                  defaultValue={
                    workspaceProjects.find((p) => p.path === detail.workspace_path)?.slug ?? ""
                  }
                  onChange={(e) => {
                    const proj = workspaceProjects.find((p) => p.slug === e.target.value);
                    void patchSelectedTask({ workspace_path: proj?.path ?? null });
                  }}
                >
                  <option value="">— none —</option>
                  {workspaceProjects.map((p) => (
                    <option key={p.slug} value={p.slug}>{p.name}</option>
                  ))}
                </select>
              </label>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <input
                ref={taskFileInputRef}
                type="file"
                multiple
                className="hidden"
                onChange={(e) => void onUploadToTask(e)}
              />
              <button
                type="button"
                disabled={uploadingTask}
                className="inline-flex items-center gap-1 border border-border bg-background px-2 py-1 hover:bg-secondary disabled:opacity-60"
                onClick={() => taskFileInputRef.current?.click()}
              >
                <Paperclip className="h-3 w-3" />
                {uploadingTask ? "Uploading…" : "Attach files"}
              </button>
              <span className="opacity-70">
                {(() => {
                  const proj = workspaceProjects.find((p) => p.path === detail.workspace_path);
                  return proj
                    ? `→ workspace/${proj.slug}/files/`
                    : "→ workspace/files/";
                })()}
              </span>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <button
                type="button"
                className="inline-flex items-center gap-1 px-2 py-1 border border-border"
                onClick={() => void retrySelectedTask()}
              >
                <Sparkles className="h-3 w-3" />
                Send to Spark
              </button>
              <button
                type="button"
                className="px-2 py-1 border border-border"
                onClick={() => void patchSelectedTask({ status: "archived" })}
              >
                Archive
              </button>
              <button type="button" className="px-2 py-1 border border-border" onClick={() => void duplicateSelectedTask()}>
                Duplicate
              </button>
              <button
                type="button"
                className="inline-flex items-center gap-1 border border-destructive/30 px-2 py-1 text-destructive hover:bg-destructive/10"
                onClick={() => void deleteSelectedTask()}
              >
                <Trash2 className="h-3 w-3" />
                Delete
              </button>
            </div>
            <div className="flex gap-2 text-xs">
              <input
                className="flex-1 border border-border bg-background px-2 py-1"
                value={completeSummary}
                onChange={(e) => setCompleteSummary(e.target.value)}
                placeholder="Review note"
              />
              <button
                type="button"
                className="px-2 py-1 border border-border"
                onClick={() => void completeSelectedTask()}
              >
                Complete
              </button>
            </div>
            <label className="block text-xs">
              <span className="mb-1 block uppercase tracking-wider opacity-70">Brief</span>
              <textarea
                key={`body-${detail.id}-${detail.updated_at ?? ""}`}
                className="min-h-32 w-full border border-border bg-background px-2 py-2"
                defaultValue={detail.body ?? ""}
                onBlur={(e) => void patchSelectedTask({ body: e.target.value })}
              />
            </label>
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
                  className="flex-1 border border-border bg-background px-2 py-1"
                  value={commentBody}
                  onChange={(e) => setCommentBody(e.target.value)}
                  placeholder="Add detail or revision note"
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
