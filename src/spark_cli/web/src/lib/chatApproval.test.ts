import { describe, expect, it } from "vitest";
import {
  approvalFailureMessage,
  approvalIsDisabled,
  approvalSubmission,
  resolveApprovalMessages,
} from "./chatApproval";
import type { ChatMessage } from "./chatTranscriptMerge";

describe("approval contract", () => {
  it("builds the choice payload without implicitly resolving all approvals", () => {
    expect(approvalSubmission({
      sessionId: "session-a",
      choice: "session",
      busy: false,
      actionId: "approval-a",
    })).toEqual({
      sessionId: "session-a",
      payload: { choice: "session", resolve_all: false, action_id: "approval-a" },
    });
  });

  it("guards missing sessions, busy submissions, and already-resolved prompts", () => {
    const input = { choice: "once" as const, busy: false, actionId: "approval-a" };
    expect(approvalSubmission({ ...input, sessionId: null })).toBeNull();
    expect(approvalSubmission({ ...input, sessionId: "session-a", busy: true })).toBeNull();
    expect(approvalSubmission({ ...input, sessionId: "session-a", resolved: true })).toBeNull();
    expect(approvalIsDisabled(true, false)).toBe(true);
    expect(approvalIsDisabled(false, true)).toBe(true);
    expect(approvalIsDisabled(false, false)).toBe(false);
  });

  it("refuses historical buttons without an exact approval identity", () => {
    const input = { sessionId: "session-a", choice: "once" as const, busy: false };
    expect(approvalSubmission(input)).toBeNull();
    expect(approvalSubmission({ ...input, actionId: "" })).toBeNull();
    expect(approvalSubmission({ ...input, actionId: "   " })).toBeNull();
    expect(approvalSubmission({ ...input, actionId: "approval-b" })?.payload.action_id).toBe("approval-b");
  });

  it("marks pending approval rows resolved while preserving other rows and identities", () => {
    const approval: ChatMessage = { id: "approval", role: "approval", approval: {} };
    const resolved: ChatMessage = { id: "resolved", role: "approval", approval: {}, resolved: true };
    const note: ChatMessage = { id: "note", role: "note", text: "waiting" };
    const result = resolveApprovalMessages([approval, resolved, note]);

    expect(result).toEqual([
      { ...approval, resolved: true },
      resolved,
      note,
    ]);
    expect(result[1]).toBe(resolved);
    expect(result[2]).toBe(note);
  });

  it("turns thrown errors into the surfaced failure message", () => {
    expect(approvalFailureMessage(new Error("No pending approval"))).toBe("No pending approval");
    expect(approvalFailureMessage("network failure")).toBe("network failure");
  });
});
