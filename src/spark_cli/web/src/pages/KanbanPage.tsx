import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  type KanbanBoardResponse,
  type KanbanTaskDetail,
  type KanbanTaskRow,
  sseUrl,
} from "@/lib/api";
import { useI18n } from "@/i18n";

const COLUMN_ORDER = ["triage", "todo", "ready", "running", "blocked", "done"] as const;

function colLabel(key: string): string {
  return key.charAt(0).toUpperCase() + key.slice(1);
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
  const [newBody, setNewBody] = useState("");
  const [commentBody, setCommentBody] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkStatus, setBulkStatus] = useState("todo");

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
      await api.bulkPatchKanbanTasks(Array.from(selectedIds), { status: bulkStatus });
      setSelectedIds(new Set());
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const createTask = async () => {
    if (!newTitle.trim() || !newAssignee.trim()) return;
    try {
      await api.createKanbanTask({
        title: newTitle.trim(),
        board: boardSlug,
        body: newBody,
        assignee: newAssignee.trim(),
      });
      setNewTitle("");
      setNewAssignee("");
      setNewBody("");
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
      await api.dispatchKanban(3, false);
      void loadBoard();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const columnTasks = useMemo(() => {
    if (!board) return {} as Record<string, KanbanTaskRow[]>;
    return board.columns;
  }, [board]);

  return (
    <div className="flex flex-col gap-4 min-h-[60vh]">
      <header className="flex flex-col gap-3 border border-border p-4 bg-background/80">
        <div className="flex flex-wrap items-center gap-2 justify-between">
          <h1 className="font-display text-lg tracking-[0.15em] uppercase text-foreground">
            {t.app.nav.kanban}
          </h1>
          <div className="flex flex-wrap gap-2 items-center">
            <button
              type="button"
              className="px-3 py-1.5 text-xs font-display uppercase tracking-wider border border-border hover:bg-foreground/5"
              onClick={() => void loadBoard()}
            >
              {t.common.refresh}
            </button>
            <button
              type="button"
              className="px-3 py-1.5 text-xs font-display uppercase tracking-wider border border-accent text-accent hover:bg-accent/10"
              onClick={() => void nudgeDispatch()}
            >
              Dispatch
            </button>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 text-sm">
          <label className="flex flex-col gap-1">
            <span className="opacity-60 text-xs uppercase tracking-wider">Board</span>
            <input
              className="border border-border bg-background px-2 py-1"
              value={boardSlug}
              onChange={(e) => setBoardSlug(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="opacity-60 text-xs uppercase tracking-wider">{t.common.search}</span>
            <input
              className="border border-border bg-background px-2 py-1"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Title, body, id"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="opacity-60 text-xs uppercase tracking-wider">Tenant</span>
            <select
              className="border border-border bg-background px-2 py-1"
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
            <span className="opacity-60 text-xs uppercase tracking-wider">Assignee</span>
            <select
              className="border border-border bg-background px-2 py-1"
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
          <div className="flex flex-wrap gap-2 items-center text-sm border-t border-border pt-3">
            <span>{selectedIds.size} selected</span>
            <select
              className="border border-border bg-background px-2 py-1"
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
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2 border-t border-border pt-3">
          <input
            className="border border-border bg-background px-2 py-1"
            placeholder="New task title"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
          />
          <input
            className="border border-border bg-background px-2 py-1"
            placeholder="Assignee (profile name)"
            value={newAssignee}
            onChange={(e) => setNewAssignee(e.target.value)}
          />
          <button
            type="button"
            className="px-3 py-1.5 border border-border hover:bg-foreground/5"
            onClick={() => void createTask()}
          >
            {t.common.create} task
          </button>
        </div>
        <textarea
          className="w-full border border-border bg-background px-2 py-1 text-sm min-h-[52px]"
          placeholder="Description (optional)"
          value={newBody}
          onChange={(e) => setNewBody(e.target.value)}
        />
      </header>

      {loading && <p className="text-sm opacity-70">{t.common.loading}</p>}
      {err && (
        <p className="text-sm text-red-400 border border-red-900/50 p-2" role="alert">
          {err}
        </p>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6 gap-3 items-start">
        {COLUMN_ORDER.map((col) => (
          <section
            key={col}
            className="border border-border bg-background/60 min-h-[280px] flex flex-col"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => void onDropColumn(e, col)}
          >
            <div className="px-2 py-2 border-b border-border font-display text-xs uppercase tracking-[0.12em] text-accent">
              {colLabel(col)} ({columnTasks[col]?.length ?? 0})
            </div>
            <div className="flex flex-col gap-1 p-2 overflow-y-auto max-h-[62vh]">
              {(columnTasks[col] ?? []).map((task) => (
                <div
                  key={task.id}
                  draggable
                  onDragStart={(e) => onDragStart(e, task.id)}
                  className={`border px-2 py-2 cursor-grab active:cursor-grabbing text-sm ${
                    selectedId === task.id ? "border-accent" : "border-border"
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
                      <div className="text-xs opacity-60 truncate">
                        {task.id} · @{String(task.assignee ?? "—")}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>

      {detail && (
        <aside className="fixed inset-y-0 right-0 w-full sm:w-[420px] border-l border-border bg-background shadow-xl z-50 flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border">
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
            </div>
            <pre className="whitespace-pre-wrap opacity-90 text-xs border border-border p-2 max-h-40 overflow-y-auto">
              {detail.body || "(no description)"}
            </pre>
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
              <ul className="text-xs space-y-1 max-h-32 overflow-y-auto opacity-90">
                {(detail.runs ?? []).map((r, idx) => (
                  <li key={idx}>{JSON.stringify(r)}</li>
                ))}
              </ul>
            </div>
          </div>
        </aside>
      )}
    </div>
  );
}
