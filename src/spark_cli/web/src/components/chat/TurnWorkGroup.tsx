import { memo, useEffect, useState } from "react";
import { AlertTriangle, Check, ChevronDown, ChevronRight, CircleDashed, Loader2 } from "lucide-react";
import type {
  TimelineApprovalItem,
  TimelineFeedbackItem,
  TimelineRequestedInputItem,
  TimelineSubagentItem,
  TimelineToolItem,
  TimelineTurn,
  TimelineWorkItem,
} from "@/lib/threadTimelineModel";
import { Markdown } from "@/components/Markdown";
import { ApprovalPrompt } from "./ApprovalPrompt";
import { FeedbackForm } from "./FeedbackForm";
import { ReasoningBubble } from "./ReasoningBubble";
import { ToolCallBubble } from "./ToolCallBubble";

export interface TurnWorkGroupProps {
  turn: TimelineTurn;
  safeMode?: boolean;
  sessionId?: string | null;
  approvalBusy?: boolean;
  onApprovalChoice?: (item: TimelineApprovalItem, choice: "once" | "session" | "always" | "deny") => void;
  onAttachPath?: (path: string) => void;
  onFetchFullResult?: (toolId: string) => Promise<string | null>;
  onSubagentSelect?: (subagentId: string) => void;
  onFeedbackSubmit?: (item: TimelineFeedbackItem, data: { name: string; email: string; area: string; note: string }) => Promise<void>;
}

function subagentStatus(status: string | undefined): string {
  return status?.trim() || "running";
}

function statusCopy(turn: TimelineTurn): string {
  switch (turn.status) {
    case "active": return "Active now";
    case "failed": return "Needs attention";
    case "interrupted": return "Interrupted";
    case "awaiting-approval": return "Approval needed";
    case "awaiting-input": return "Input needed";
    default: return "Completed work";
  }
}

function statusIcon(turn: TimelineTurn) {
  if (turn.status === "failed" || turn.status === "awaiting-approval" || turn.status === "awaiting-input") {
    return <AlertTriangle className="h-3.5 w-3.5" />;
  }
  if (turn.status === "active") return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
  if (turn.status === "interrupted") return <CircleDashed className="h-3.5 w-3.5" />;
  return <Check className="h-3.5 w-3.5" />;
}

function ToolItem({ item, safeMode, onAttachPath, onFetchFullResult }: {
  item: TimelineToolItem;
  safeMode: boolean;
  onAttachPath?: (path: string) => void;
  onFetchFullResult?: (toolId: string) => Promise<string | null>;
}) {
  return (
    <ToolCallBubble
      name={item.name}
      args={{ ...item.args }}
      result={item.result}
      resultTruncated={item.resultTruncated}
      done={item.done}
      safeMode={safeMode}
      onAttachPath={onAttachPath}
      onFetchFullResult={onFetchFullResult ? () => onFetchFullResult(item.toolId) : undefined}
    />
  );
}

function ApprovalItem({ item, disabled, onChoice }: {
  item: TimelineApprovalItem;
  disabled: boolean;
  onChoice?: TurnWorkGroupProps["onApprovalChoice"];
}) {
  const command = String(item.approval.command ?? "");
  const description = String(item.approval.description ?? "");
  if (item.resolved) {
    return <div className="rounded-lg border border-success/25 bg-success/8 px-3 py-2 text-xs text-success/80">Approval resolved{command ? ` · ${command}` : ""}</div>;
  }
  return (
    <ApprovalPrompt
      command={command}
      description={description}
      disabled={disabled || item.resolved || !onChoice}
      onChoice={(choice) => onChoice?.(item, choice)}
    />
  );
}

function RequestedInputItem({ item }: { item: TimelineRequestedInputItem }) {
  if (item.requestedInput.resolved) {
    return <div className="rounded-lg border border-success/25 bg-success/8 px-3 py-2 text-xs text-success/80">Input received · {item.requestedInput.prompt}</div>;
  }
  return (
    <div role="status" className="rounded-lg border border-amber-400/35 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
      <div className="font-semibold uppercase tracking-[0.12em] text-[10px] text-amber-300">Input needed</div>
      <p className="mt-1 leading-5">{item.requestedInput.prompt}</p>
    </div>
  );
}

function SubagentItem({ item }: { item: TimelineSubagentItem }) {
  const status = subagentStatus(item.subagent.status);
  return (
    <div className="flex items-start gap-2 rounded-md border border-primary/15 bg-primary/5 px-3 py-2 text-xs">
      <span className={`mt-0.5 h-2 w-2 shrink-0 rounded-full ${/failed|error/i.test(status) ? "bg-destructive" : /active|running|starting/i.test(status) ? "bg-success animate-pulse" : "bg-primary/70"}`} />
      <div className="min-w-0">
        <div className="font-medium text-foreground">{item.subagent.name ?? item.subagent.id}</div>
        {item.subagent.task && <div className="truncate text-muted-foreground">{item.subagent.task}</div>}
        <div className="mt-0.5 text-[10px] uppercase tracking-wider text-muted-foreground/60">{status}</div>
      </div>
    </div>
  );
}

function WorkItem({ item, safeMode, approvalBusy, onApprovalChoice, onAttachPath, onFetchFullResult, onFeedbackSubmit }: {
  item: TimelineWorkItem;
  safeMode: boolean;
  approvalBusy: boolean;
  onApprovalChoice?: TurnWorkGroupProps["onApprovalChoice"];
  onAttachPath?: (path: string) => void;
  onFetchFullResult?: (toolId: string) => Promise<string | null>;
  onFeedbackSubmit?: TurnWorkGroupProps["onFeedbackSubmit"];
}) {
  switch (item.kind) {
    case "reasoning":
      return <ReasoningBubble text={item.text} isActive={false} safeMode={safeMode} />;
    case "tool":
      return <ToolItem item={item} safeMode={safeMode} onAttachPath={onAttachPath} onFetchFullResult={onFetchFullResult} />;
    case "approval":
      return <ApprovalItem item={item} disabled={approvalBusy} onChoice={onApprovalChoice} />;
    case "requested-input":
      return <RequestedInputItem item={item} />;
    case "feedback":
      return <FeedbackForm submitted={item.submitted} onSubmit={(data) => onFeedbackSubmit?.(item, data) ?? Promise.resolve()} />;
    case "subagent":
      return <SubagentItem item={item} />;
    case "assistant":
      return <div className="rounded-md border border-border/50 bg-background/35 px-3 py-2 text-sm"><Markdown content={item.content} safeMode={safeMode} /></div>;
    case "note":
      return <p className="px-1 text-xs italic text-muted-foreground">{item.text}</p>;
  }
}

export const TurnWorkGroup = memo(function TurnWorkGroup({
  turn,
  safeMode = false,
  approvalBusy = false,
  onApprovalChoice,
  onAttachPath,
  onFetchFullResult,
  onSubagentSelect,
  onFeedbackSubmit,
}: TurnWorkGroupProps) {
  const hasWork = turn.workItems.length > 0 || turn.subagents.length > 0;
  const [open, setOpen] = useState(turn.isExpanded);

  useEffect(() => {
    setOpen(turn.isExpanded);
  }, [turn.id, turn.isExpanded]);

  if (!hasWork) return null;

  const visibleWork = turn.workItems.filter((item) => item.kind !== "subagent");
  return (
    <section className="ml-8 mt-1 max-w-[85%]" data-turn-work-group={turn.id} data-state={turn.status}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={`${turn.id}-work`}
        className="flex w-full items-center gap-2 rounded-md border border-border/55 bg-foreground/[0.025] px-3 py-2 text-left text-xs transition hover:border-primary/30 hover:bg-foreground/[0.05] focus:outline-none focus:ring-1 focus:ring-ring"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        <span className="flex items-center gap-1.5 text-muted-foreground">{statusIcon(turn)}<span>{statusCopy(turn)}</span></span>
        <span className="ml-auto truncate text-[10px] tabular-nums text-muted-foreground/60">{turn.workSummary.label}</span>
      </button>
      {open && (
        <div id={`${turn.id}-work`} className="mt-2 space-y-2 border-l border-border/55 pl-3">
          {turn.subagents.length > 0 && (
            <div className="space-y-2" data-testid="turn-subagents">
              {turn.subagents.map((subagent) => (
                <button
                  key={subagent.id}
                  type="button"
                  className="block w-full text-left disabled:cursor-default"
                  disabled={!onSubagentSelect}
                  onClick={() => onSubagentSelect?.(subagent.id)}
                >
                  <SubagentItem item={{ kind: "subagent", id: `${turn.id}:subagent:${subagent.id}`, subagent, sourceMessageIds: [subagent.id] }} />
                </button>
              ))}
            </div>
          )}
          {visibleWork.map((item) => (
            <div key={item.id} data-work-item={item.kind}>
              <WorkItem
                item={item}
                safeMode={safeMode}
                approvalBusy={approvalBusy}
                onApprovalChoice={onApprovalChoice}
                onAttachPath={onAttachPath}
                onFetchFullResult={onFetchFullResult}
                onFeedbackSubmit={onFeedbackSubmit}
              />
            </div>
          ))}
        </div>
      )}
    </section>
  );
});
