import { type KeyboardEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Loader2,
  TerminalSquare,
  Wrench,
  X,
} from "lucide-react";
import { api, type SubagentEvent, type SubagentRun, type SubagentStatus } from "@/lib/api";
import {
  isSubagentRunning,
  sortSubagents,
  subagentDisplayName,
  subagentTimestamp,
  subagentVisual,
} from "@/lib/subagents";
import { cn } from "@/lib/utils";
import { Markdown } from "@/components/Markdown";
import { ReasoningBubble } from "@/components/chat/ReasoningBubble";
import { StatusPill } from "@/components/chat/StatusPill";
import { ToolCallBubble } from "@/components/chat/ToolCallBubble";

// The v1 sub-agent inspector is read-only: it reuses the chat Markdown,
// reasoning, tool, and status visuals, while PromptBar stays with parent chat
// until the backend exposes child follow-up routing.

interface SubagentsPanelProps {
  subagents: SubagentRun[];
  selectedId: string | null;
  loading: boolean;
  error: string | null;
  sessionId?: string | null;
  onSelect: (id: string) => void;
  onCloseDetail: () => void;
}

function firstString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function statusLabel(status: SubagentStatus | null | undefined): string {
  if (status === "completed") return "done";
  if (status === "failed") return "failed";
  if (status === "cancelled" || status === "interrupted") return "stopped";
  if (status === "queued" || status === "starting") return "starting";
  return "running sub-agent";
}

function statusClasses(status: SubagentStatus | null | undefined): string {
  if (status === "completed") return "border-emerald-400/25 bg-emerald-400/10 text-emerald-300";
  if (status === "failed") return "border-red-400/25 bg-red-400/10 text-red-300";
  if (status === "cancelled" || status === "interrupted") {
    return "border-amber-400/25 bg-amber-400/10 text-amber-300";
  }
  if (status === "queued" || status === "starting") {
    return "border-sky-400/25 bg-sky-400/10 text-sky-300";
  }
  return "border-primary/20 bg-primary/10 text-primary";
}

function StatusIcon({ status }: { status: SubagentStatus | null | undefined }) {
  if (status === "completed") return <CheckCircle2 className="h-3.5 w-3.5" />;
  if (status === "failed") return <AlertTriangle className="h-3.5 w-3.5" />;
  if (status === "cancelled" || status === "interrupted") return <CircleDashed className="h-3.5 w-3.5" />;
  return <Loader2 className={cn("h-3.5 w-3.5", isSubagentRunning(status) && "animate-spin")} />;
}

function formatElapsed(run: SubagentRun, nowSeconds: number): string {
  const recordedDuration =
    typeof run.elapsed_seconds === "number" && Number.isFinite(run.elapsed_seconds)
      ? run.elapsed_seconds
      : typeof run.duration_seconds === "number" && Number.isFinite(run.duration_seconds)
      ? run.duration_seconds
      : null;
  if (recordedDuration !== null && !isSubagentRunning(run.status)) {
    return formatDuration(recordedDuration);
  }
  const start = run.started_at ?? null;
  if (!start) return "0s";
  const end = run.ended_at ?? (isSubagentRunning(run.status) ? nowSeconds : run.updated_at ?? nowSeconds);
  return formatDuration(Math.max(0, end - start));
}

function formatDuration(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(total / 60);
  const secs = total % 60;
  if (mins >= 60) {
    const hours = Math.floor(mins / 60);
    const remMins = mins % 60;
    return `${hours}h ${remMins}m`;
  }
  return mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
}

function eventType(event: SubagentEvent): string {
  return String(event.type ?? event.kind ?? event.event_type ?? event.role ?? "event");
}

function eventPayload(event: SubagentEvent): Record<string, unknown> {
  const data = asRecord(event.data);
  return asRecord(data.payload && typeof data.payload === "object" ? data.payload : data);
}

function toolArgs(event: SubagentEvent): Record<string, unknown> {
  const payload = eventPayload(event);
  return asRecord(payload.args);
}

function toolResult(event: SubagentEvent): string | null {
  const payload = eventPayload(event);
  return firstString(payload.result, payload.output, payload.preview, event.text, event.content, event.message);
}

function toolPreview(event: SubagentEvent): string | null {
  const payload = eventPayload(event);
  const args = asRecord(payload.args);
  const urls = Array.isArray(args.urls) ? args.urls.filter((item) => typeof item === "string") : [];
  return firstString(
    payload.preview,
    args.query,
    args.q,
    args.url,
    urls.length > 0 ? urls.slice(0, 3).join("\n") : null,
    event.text,
    event.content,
    event.message,
  );
}

function timelineCopy(event: SubagentEvent, run: SubagentRun): { title: string; body: string | null; tone: "normal" | "tool" | "success" | "error" } {
  const rawType = eventType(event);
  const type = rawType.replace(/^subagent\./, "");
  const payload = eventPayload(event);
  const tool = firstString(event.tool_name, payload.tool, payload.tool_name);
  const preview = toolPreview(event);
  const duration = firstNumber(payload.duration_seconds, payload.duration);

  if (type === "created") {
    return { title: "Started task", body: run.task ?? run.goal ?? null, tone: "normal" };
  }
  if (type === "started") {
    return { title: "Running sub-agent", body: "Preparing tools and gathering context.", tone: "normal" };
  }
  if (type === "thinking") {
    return { title: "Thinking", body: preview ?? "Working through the next step.", tone: "normal" };
  }
  if (type === "tool_started") {
    return { title: `Running ${tool ?? "tool"}`, body: preview, tone: "tool" };
  }
  if (type === "tool_completed") {
    const lines = firstNumber(payload.result_lines);
    const bits = [
      duration !== null ? `Finished in ${duration.toFixed(1)}s.` : "Finished.",
      lines !== null ? `${lines} output line${lines === 1 ? "" : "s"}.` : null,
      preview,
    ].filter(Boolean);
    return { title: `Finished ${tool ?? "tool"}`, body: bits.join(" "), tone: "tool" };
  }
  if (type === "completed") {
    return { title: "Completed", body: firstString(payload.summary, run.summary) ?? "Finished successfully.", tone: "success" };
  }
  if (type === "failed") {
    return { title: "Failed", body: firstString(payload.error, run.error) ?? "The sub-agent hit an error.", tone: "error" };
  }
  if (type === "interrupted") {
    return { title: "Stopped", body: firstString(payload.error, payload.summary) ?? "The sub-agent was interrupted.", tone: "error" };
  }
  return {
    title: rawType.replace(/_/g, " "),
    body: firstString(event.text, event.content, event.message, preview) ?? "Received an update.",
    tone: "normal",
  };
}

function eventIcon(tone: "normal" | "tool" | "success" | "error") {
  if (tone === "tool") return <Wrench className="h-3.5 w-3.5" />;
  if (tone === "success") return <CheckCircle2 className="h-3.5 w-3.5" />;
  if (tone === "error") return <AlertTriangle className="h-3.5 w-3.5" />;
  return <TerminalSquare className="h-3.5 w-3.5" />;
}

function SubagentRow({
  run,
  index,
  selected,
  nowSeconds,
  onSelect,
  onKeyDown,
}: {
  run: SubagentRun;
  index: number;
  selected: boolean;
  nowSeconds: number;
  onSelect: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
}) {
  const visual = subagentVisual(run.id);
  const name = subagentDisplayName(run, index);
  const glyph = firstString(run.short_name, name.slice(0, 1), visual.glyph) ?? "A";
  return (
    <button
      type="button"
      data-subagent-row
      onClick={onSelect}
      onKeyDown={onKeyDown}
      aria-current={selected ? "true" : undefined}
      aria-label={`${name}, ${statusLabel(run.status)}, ${formatElapsed(run, nowSeconds)}`}
      className={cn(
        "flex w-full min-w-0 items-start gap-2 border-l-2 px-3 py-2 text-left transition",
        selected
          ? "border-l-primary bg-foreground/8"
          : "border-l-transparent hover:bg-foreground/6",
      )}
    >
      <span
        className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md border text-[11px] font-semibold"
        style={{ borderColor: visual.accent, background: visual.bg, color: visual.fg }}
      >
        {glyph}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-xs font-medium text-foreground">{name}</span>
          <span className="ml-auto shrink-0 text-[10px] text-muted-foreground/60">
            {formatElapsed(run, nowSeconds)}
          </span>
        </span>
        <span className="mt-1 flex min-w-0 items-center">
          <span className={cn("inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px]", statusClasses(run.status))}>
            <StatusIcon status={run.status} />
            {statusLabel(run.status)}
          </span>
        </span>
        <span className="mt-1 block min-w-0 truncate text-[11px] text-muted-foreground/70">
          {run.task ?? run.summary ?? run.error ?? "Working"}
        </span>
      </span>
    </button>
  );
}

function AggregateSummary({ subagents }: { subagents: SubagentRun[] }) {
  const counts = useMemo(() => {
    let working = 0;
    let completed = 0;
    let failed = 0;
    let stopped = 0;
    for (const run of subagents) {
      if (run.status === "completed") completed += 1;
      else if (run.status === "failed") failed += 1;
      else if (run.status === "cancelled" || run.status === "interrupted") stopped += 1;
      else if (isSubagentRunning(run.status)) working += 1;
    }
    return { working, completed, failed, stopped };
  }, [subagents]);

  const parts = [
    counts.working ? `${counts.working} working` : null,
    counts.completed ? `${counts.completed} done` : null,
    counts.failed ? `${counts.failed} failed` : null,
    counts.stopped ? `${counts.stopped} stopped` : null,
  ].filter(Boolean);

  if (parts.length === 0) return null;

  return (
    <div className="flex items-center gap-2 border-b border-border px-3 py-2">
      <div className="min-w-0 flex-1">
        <div className="truncate text-[11px] text-muted-foreground/65">{parts.join(" · ")}</div>
      </div>
    </div>
  );
}

function TaskCard({ run }: { run: SubagentRun }) {
  const [expanded, setExpanded] = useState(false);
  const task = run.task ?? run.goal ?? "Sub-agent task";
  const isLong = task.length > 520;
  const visibleTask = !isLong || expanded ? task : `${task.slice(0, 520).trimEnd()}...`;

  return (
    <div className="mb-3 rounded-md border border-border/70 bg-card/35 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase text-muted-foreground/55">Task</div>
      <div className="mt-1 text-xs leading-5 text-foreground/90">
        <Markdown content={visibleTask} />
      </div>
      {isLong && (
        <button
          type="button"
          className="mt-2 rounded px-1.5 py-0.5 text-[11px] font-medium text-muted-foreground transition hover:bg-secondary hover:text-foreground"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

function SubagentDetail({
  run,
  index,
  nowSeconds,
  sessionId,
  onClose,
}: {
  run: SubagentRun;
  index: number;
  nowSeconds: number;
  sessionId?: string | null;
  onClose: () => void;
}) {
  const [interrupting, setInterrupting] = useState(false);
  const [interruptError, setInterruptError] = useState<string | null>(null);
  const name = subagentDisplayName(run, index);
  const visual = subagentVisual(run.id);
  const glyph = firstString(run.short_name, name.slice(0, 1), visual.glyph) ?? "A";
  const events = useMemo(
    () => sortEvents(run.events?.length ? run.events : run.transcript ?? []),
    [run],
  );
  const streaming = isSubagentRunning(run.status);
  const canInterrupt = Boolean(sessionId && streaming);

  const interrupt = async () => {
    if (!sessionId || interrupting) return;
    setInterrupting(true);
    setInterruptError(null);
    try {
      await api.interruptConversationSubagent(sessionId, run.id, "Stop this sub-agent.");
    } catch (err) {
      setInterruptError(err instanceof Error ? err.message : "Could not stop this sub-agent.");
    } finally {
      setInterrupting(false);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background/40">
      <div className="flex min-h-[64px] shrink-0 items-center gap-2.5 border-b border-border px-2.5 py-2">
        <button
          type="button"
          aria-label="Back to subagents"
          title="Back to subagents"
          onClick={onClose}
          className="grid h-7 w-7 place-items-center rounded text-muted-foreground transition hover:bg-secondary hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
        </button>
        <span
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md border text-[11px] font-semibold"
          style={{ borderColor: visual.accent, background: visual.bg, color: visual.fg }}
        >
          {glyph}
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-xs font-medium text-foreground">{name}</span>
            <span className="ml-auto inline-flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
              <Clock3 className="h-3.5 w-3.5" />
              {formatElapsed(run, nowSeconds)}
            </span>
          </div>
          <div className="flex min-w-0 items-center gap-2">
            <StatusPill streaming={streaming} label={streaming ? statusLabel(run.status) : statusLabel(run.status)} />
            {run.model && (
              <span className="min-w-0 truncate font-mono-ui text-[10px] text-muted-foreground/65">
                {run.model}
              </span>
            )}
          </div>
        </div>
        {canInterrupt && (
          <button
            type="button"
            aria-label="Stop subagent"
            title="Stop subagent"
            onClick={() => void interrupt()}
            disabled={interrupting}
            className="grid h-7 w-7 place-items-center rounded text-muted-foreground transition hover:bg-secondary hover:text-foreground disabled:opacity-50"
          >
            {interrupting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CircleDashed className="h-3.5 w-3.5" />}
          </button>
        )}
        <button
          type="button"
          aria-label="Close subagent thread"
          title="Close subagent thread"
          onClick={onClose}
          className="grid h-7 w-7 place-items-center rounded text-muted-foreground transition hover:bg-secondary hover:text-foreground"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {interruptError && (
          <div className="mb-3 rounded-md border border-red-400/20 bg-red-400/5 px-3 py-2 text-xs text-red-300">
            {interruptError}
          </div>
        )}
        <TaskCard run={run} />

        {events.length === 0 ? (
          <div className="rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground/60">
            Waiting for the first update.
          </div>
        ) : (
          <div className="space-y-2">
            {events.map((event, eventIndex) => {
              const copy = timelineCopy(event, run);
              const type = eventType(event).replace(/^subagent\./, "");
              const tool = firstString(event.tool_name, eventPayload(event).tool, eventPayload(event).tool_name);
              if (type === "thinking" && copy.body) {
                return (
                  <ReasoningBubble
                    key={`${subagentTimestamp(event)}:${eventType(event)}:${eventIndex}`}
                    text={copy.body}
                    isActive={streaming}
                  />
                );
              }
              if ((type === "tool_started" || type === "tool_completed") && tool) {
                return (
                  <ToolCallBubble
                    key={`${subagentTimestamp(event)}:${eventType(event)}:${eventIndex}`}
                    name={tool}
                    args={toolArgs(event)}
                    result={type === "tool_completed" ? toolResult(event) ?? undefined : undefined}
                    done={type === "tool_completed"}
                    durationSeconds={firstNumber(eventPayload(event).duration_seconds, eventPayload(event).duration) ?? undefined}
                  />
                );
              }
              return (
                <div
                  key={`${subagentTimestamp(event)}:${eventType(event)}:${eventIndex}`}
                  className={cn(
                    "rounded-md border px-3 py-2",
                    copy.tone === "success" && "border-emerald-400/20 bg-emerald-400/5",
                    copy.tone === "error" && "border-red-400/20 bg-red-400/5",
                    copy.tone === "tool" && "border-border/70 bg-card/35",
                    copy.tone === "normal" && "border-border/70 bg-background/35",
                  )}
                >
                  <div className="mb-1 flex items-center gap-1.5 text-[10px] uppercase text-muted-foreground/60">
                    {eventIcon(copy.tone)}
                    <span className="truncate">{copy.title}</span>
                  </div>
                  {copy.body && (
                    <div className="text-xs leading-5 text-foreground/85">
                      <Markdown content={copy.body} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function sortEvents(events: SubagentEvent[]): SubagentEvent[] {
  return [...events].sort((a, b) => {
    const delta = subagentTimestamp(a) - subagentTimestamp(b);
    if (delta !== 0) return delta;
    return eventType(a).localeCompare(eventType(b));
  });
}

export function SubagentsPanel({
  subagents,
  selectedId,
  loading,
  error,
  sessionId,
  onSelect,
  onCloseDetail,
}: SubagentsPanelProps) {
  const [nowSeconds, setNowSeconds] = useState(() => Date.now() / 1000);
  const sorted = useMemo(() => sortSubagents(subagents), [subagents]);
  const selectedIndex = sorted.findIndex((run) => run.id === selectedId);
  const selectedRun = selectedIndex >= 0 ? sorted[selectedIndex] : null;
  const hasRunning = sorted.some((run) => isSubagentRunning(run.status));

  useEffect(() => {
    if (!hasRunning) return;
    const timer = window.setInterval(() => setNowSeconds(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [hasRunning]);

  const handleRowKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const buttons = Array.from(
      event.currentTarget.closest("[data-subagent-list]")?.querySelectorAll<HTMLButtonElement>("[data-subagent-row]") ?? [],
    );
    const index = buttons.indexOf(event.currentTarget);
    const next = event.key === "ArrowDown" ? buttons[index + 1] ?? buttons[0] : buttons[index - 1] ?? buttons[buttons.length - 1];
    next?.focus();
  };

  if (selectedRun) {
    return (
      <SubagentDetail
        run={selectedRun}
        index={selectedIndex}
        nowSeconds={nowSeconds}
        sessionId={sessionId}
        onClose={onCloseDetail}
      />
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background/40">
      <AggregateSummary subagents={sorted} />
      {error && (
        <div className="border-b border-border px-3 py-2 text-[11px] leading-4 text-red-300">
          {error}
        </div>
      )}
      <div data-subagent-list className="min-h-0 flex-1 overflow-y-auto py-1" role="list" aria-label="Subagents">
        {sorted.map((run, index) => (
          <SubagentRow
            key={run.id}
            run={run}
            index={index}
            selected={run.id === selectedId}
            nowSeconds={nowSeconds}
            onSelect={() => onSelect(run.id)}
            onKeyDown={handleRowKeyDown}
          />
        ))}
        {sorted.length === 0 && (
          <div className="flex items-center gap-2 px-3 py-3 text-xs text-muted-foreground">
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bot className="h-3.5 w-3.5" />}
            {loading ? "Loading subagents" : "No subagents for this thread yet."}
          </div>
        )}
      </div>
    </div>
  );
}
