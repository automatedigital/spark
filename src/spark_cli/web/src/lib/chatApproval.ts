import type { ChatMessage } from "./chatTranscriptMerge";

export type ApprovalChoice = "once" | "session" | "always" | "deny";

export interface ApprovalSubmission {
  sessionId: string;
  payload: {
    choice: ApprovalChoice;
    resolve_all: boolean;
  };
}

export function approvalIsDisabled(busy: boolean, resolved: boolean): boolean {
  return busy || resolved;
}

export function approvalSubmission(input: {
  sessionId: string | null | undefined;
  choice: ApprovalChoice;
  busy: boolean;
  resolved?: boolean;
}): ApprovalSubmission | null {
  if (!input.sessionId || input.busy || input.resolved) return null;

  return {
    sessionId: input.sessionId,
    payload: {
      choice: input.choice,
      resolve_all: false,
    },
  };
}

export function resolveApprovalMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((message) => (
    message.role === "approval" && !message.resolved
      ? { ...message, resolved: true }
      : message
  ));
}

export function approvalFailureMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
