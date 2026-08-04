import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SessionInfoBar } from "./SessionInfoBar";

describe("SessionInfoBar accessibility disclosure", () => {
  it("starts collapsed with an expand chevron and disclosure metadata", () => {
    const html = renderToStaticMarkup(createElement(SessionInfoBar, {
      stats: { model: "sol", inputTokens: 120 },
    }));

    expect(html).toContain('aria-expanded="false"');
    expect(html).toMatch(/aria-controls="session-stats-[^"]+"/);
    expect(html).toContain("lucide-chevron-down");
    expect(html).not.toContain("lucide-chevron-up");
  });
});
