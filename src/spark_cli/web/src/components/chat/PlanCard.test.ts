import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { PlanCard } from "./PlanCard";

describe("PlanCard", () => {
  it("shows status, step progress, markdown, and the full-plan action", () => {
    const onOpenPlan = vi.fn();
    const html = renderToStaticMarkup(createElement(PlanCard, {
      plan: {
        revision: 2,
        status: "active",
        markdown: "Keep the implementation focused.",
        steps: [
          { id: "one", content: "Ship the contract", status: "completed" },
          { id: "two", content: "Wire the panel", status: "in_progress" },
        ],
      },
      onOpenPlan,
    }));
    expect(html).toContain("Plan");
    expect(html).toContain("In progress");
    expect(html).toContain("1/2");
    expect(html).toContain("Ship the contract");
    expect(html).toContain("Keep the implementation focused.");
    expect(html).toContain('aria-label="Open full plan"');
  });
});
