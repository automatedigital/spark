import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { PendingActionTray } from "./PendingActionTray";

const base = { session_id: "s1", turn_id: "t1", status: "pending" as const, created_at: 1 };

describe("PendingActionTray", () => {
  it("keeps durable approvals and requested input above a distinct surface", () => {
    const html = renderToStaticMarkup(createElement(PendingActionTray, {
      actions: [
        { ...base, action_id: "approval-1", kind: "approval", payload: { command: "git push", description: "Publish the branch" } },
        { ...base, action_id: "input-1", kind: "requested_input", payload: { question: "Which environment?", choices: ["staging", "production"] } },
      ],
      onApprovalChoice: vi.fn(),
      onSubmitInput: vi.fn(),
    }));
    expect(html).toContain('data-testid="pending-action-tray"');
    expect(html).toContain('data-action-id="approval-1"');
    expect(html).toContain("Allow once");
    expect(html).toContain("Which environment?");
    expect(html).toContain("staging");
    expect(html).toContain('aria-label="Pending actions"');
  });

  it("hides resolved actions and an empty tray", () => {
    const html = renderToStaticMarkup(createElement(PendingActionTray, {
      actions: [{ ...base, action_id: "resolved", kind: "approval", status: "resolved", payload: {} }],
    }));
    expect(html).toBe("");
  });
});
