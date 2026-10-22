import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChangeRow } from "./WorkspaceChangesPanel";

describe("Git filename transport rows", () => {
  it("renders byte-name labels and disables their discard action", () => {
    const html = renderToStaticMarkup(createElement(ChangeRow, {
      slug: "repo", onReverted: () => {},
      file: { path: "", display_path: "b'invalid-\\xff.txt'", unsupported_reason: "Filename is not valid UTF-8; use Git directly", status: "deleted", adds: 0, dels: 1 },
    }));
    expect(html).toContain("invalid-\\xff.txt");
    expect(html).toContain('disabled=""');
    expect(html).toContain("Filename is not valid UTF-8; use Git directly");
  });

  it("keeps a Unicode neighbor actionable with its exact filename", () => {
    const html = renderToStaticMarkup(createElement(ChangeRow, {
      slug: "repo", onReverted: () => {},
      file: { path: "雪\tneighbor.txt", status: "modified", adds: 1, dels: 1 },
    }));
    expect(html).toContain("雪\tneighbor.txt");
    expect(html).toContain('title="Revert file"');
    expect(html).not.toContain('disabled=""');
  });
});
