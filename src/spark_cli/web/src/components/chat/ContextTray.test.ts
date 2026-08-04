import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ContextTray } from "./ContextTray";

describe("ContextTray accessibility affordances", () => {
  it("keeps file actions available to keyboard and coarse-pointer users", () => {
    const html = renderToStaticMarkup(createElement(ContextTray, {
      items: [{
        id: "file-1",
        type: "file",
        source_path: "/repo/README.md",
        inclusion_mode: "full",
        scope: "one_turn",
        size_bytes: 120,
      }],
      onRemove: () => {},
      onUpdateMode: () => {},
      onUpdateScope: () => {},
      onSummarize: () => {},
    }));

    expect(html).toContain("focus-visible:opacity-100");
    expect(html).toContain("[@media(pointer:coarse)]:opacity-100");
    expect(html).toContain('title="Summarize this file"');
    expect(html).toContain('title="Pin across turns"');
    expect(html).toContain('title="Remove"');
  });
});
