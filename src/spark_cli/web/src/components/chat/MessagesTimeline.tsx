import { memo } from "react";
import { MessageSquare } from "lucide-react";
import type { TimelineAssistantMessage, TimelineApprovalItem, TimelineTurn } from "@/lib/threadTimelineModel";
import { cn } from "@/lib/utils";
import { AssistantMessageRow } from "./AssistantMessageRow";
import { TurnWorkGroup, type TurnWorkGroupProps } from "./TurnWorkGroup";
import { UserMessageRow } from "./UserMessageRow";

export interface MessagesTimelineProps extends Pick<TurnWorkGroupProps, "safeMode" | "sessionId" | "approvalBusy" | "onApprovalChoice" | "onAttachPath" | "onFetchFullResult" | "onSubagentSelect" | "onFeedbackSubmit"> {
  turns: readonly TimelineTurn[];
  hasSession?: boolean;
  streaming?: boolean;
  defaultWrap?: boolean;
  onEdit?: (sessionIdx: number, text: string) => void;
  onRetry?: (sessionIdx: number) => void;
  onFork?: (sessionIdx: number) => void;
  onCopyText?: (text: string) => void;
  onPromoteToBrief?: (message: TimelineAssistantMessage) => void;
  onCopyExact?: (message: TimelineAssistantMessage) => void;
  className?: string;
  emptyLabel?: string;
}

export function TimelineTurnGroup({
  turn,
  hasSession,
  streaming,
  defaultWrap,
  safeMode,
  sessionId,
  approvalBusy,
  onApprovalChoice,
  onAttachPath,
  onFetchFullResult,
  onSubagentSelect,
  onFeedbackSubmit,
  onEdit,
  onRetry,
  onFork,
  onCopyText,
  onPromoteToBrief,
  onCopyExact,
}: Omit<MessagesTimelineProps, "turns" | "className" | "emptyLabel"> & { turn: TimelineTurn }) {
  return (
    <article className="space-y-3" data-turn-id={turn.id} data-turn-status={turn.status}>
      {turn.userMessage && (
        <UserMessageRow
          message={turn.userMessage}
          hasSession={hasSession}
          streaming={streaming}
          onEdit={onEdit}
          onRetry={onRetry}
          onFork={onFork}
          onCopy={onCopyText}
        />
      )}
      {turn.finalAnswer && (
        <AssistantMessageRow
          message={turn.finalAnswer}
          safeMode={safeMode}
          defaultWrap={defaultWrap}
          onPromoteToBrief={onPromoteToBrief}
          onCopyExact={onCopyExact}
        />
      )}
      <TurnWorkGroup
        turn={turn}
        safeMode={safeMode}
        sessionId={sessionId}
        approvalBusy={approvalBusy}
        onApprovalChoice={onApprovalChoice}
        onAttachPath={onAttachPath}
        onFetchFullResult={onFetchFullResult}
        onSubagentSelect={onSubagentSelect}
        onFeedbackSubmit={onFeedbackSubmit}
      />
    </article>
  );
}

export const MessagesTimeline = memo(function MessagesTimeline({
  turns,
  className,
  emptyLabel = "Start a conversation",
  ...props
}: MessagesTimelineProps) {
  if (turns.length === 0) {
    return (
      <div className={cn("flex min-h-[16rem] flex-col items-center justify-center text-muted-foreground", className)} data-testid="messages-timeline-empty">
        <MessageSquare className="mb-3 h-8 w-8 opacity-30" aria-hidden="true" />
        <p className="text-sm">{emptyLabel}</p>
      </div>
    );
  }

  return (
    <section className={cn("mx-auto w-full max-w-3xl px-4 py-5 pr-8", className)} aria-label="Conversation thread" data-testid="messages-timeline">
      <div className="space-y-7">
        {turns.map((turn) => <TimelineTurnGroup key={turn.id} turn={turn} {...props} />)}
      </div>
    </section>
  );
});

export type { TimelineApprovalItem };
