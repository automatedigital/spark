import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ChangedFilesCard } from "./ChangedFilesCard";

describe("ChangedFilesCard", () => {
  it("renders compact file stats and an accessible open action", () => {
    const onOpenFile = vi.fn();
    const html = renderToStaticMarkup(createElement(ChangedFilesCard, {
      changedFiles: {
        is_repo: true,
        branch: "feature/thread-ui",
        count: 1,
        files: [{ path: "src/chat.tsx", status: "modified", after: { adds: 12, dels: 3 } }],
      },
      onOpenFile,
    }));
    expect(html).toContain("Files changed");
    expect(html).toContain("src/chat.tsx");
    expect(html).toContain("12 additions");
    expect(html).toContain("3 deletions");
    expect(html).toContain('aria-label="Open src/chat.tsx"');
  });

  it("does not render an empty outcome card", () => {
    expect(renderToStaticMarkup(createElement(ChangedFilesCard, { changedFiles: { is_repo: true, branch: null, count: 0, files: [] } }))).toBe("");
  });
});
