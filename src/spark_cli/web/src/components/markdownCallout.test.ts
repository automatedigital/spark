import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";
import { blockPropsEqual, buildMarkdownRenderSegments, parseBlocks, parseCallout } from "./markdownParse";

const kinds = ["NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION"] as const;
const render = (content: string, streaming = false, safeMode = false) =>
  renderToStaticMarkup(createElement(Markdown, { content, streaming, safeMode }));

describe("GitHub callouts", () => {
  it.each(kinds)("parses and labels %s without relying on color or live alerts", (kind) => {
    const source = `> [!${kind}]\n> **Read** this.\n> Second line.`;
    expect(parseBlocks(source)).toEqual([{ type: "callout", kind, content: "**Read** this.\nSecond line." }]);
    const html = render(source);
    expect(html).toContain('role="note"');
    expect(html).toMatch(/aria-labelledby="([^"]+)"/);
    const id = html.match(/aria-labelledby="([^"]+)"/)![1];
    expect(html).toContain(`id="${id}"`);
    expect(html).toContain(kind[0] + kind.slice(1).toLowerCase());
    expect(html).toContain('aria-hidden="true"');
    expect(html).toMatch(/<strong[^>]*>Read<\/strong>/);
    expect(html).not.toContain("[!");
    expect(html).not.toContain('role="alert"');
    expect(html).toContain("text-foreground");
    expect(html).toContain("bg-background");
  });

  it("preserves ordinary, unknown, misplaced, escaped and incomplete markers", () => {
    for (const content of ["ordinary\nquote", "[!CUSTOM]\nbody", "prefix [!NOTE]", "[!NOTE] suffix", "[!NOT", "\\[!NOTE]", "[!note]", "intro\n[!TIP]"]) {
      expect(parseBlocks(content.split("\n").map((line) => `> ${line}`).join("\n")))
        .toEqual([{ type: "blockquote", content }]);
    }
    expect(parseCallout("[!NOTE]\r\nbody")).toEqual({ type: "callout", kind: "NOTE", content: "body" });
    expect(render("> ordinary")).toContain("<blockquote");
  });

  it("renders body paragraphs, lists, nested quotes and fences safely", () => {
    const source = "> [!WARNING]\n> First\n>\n> - one\n> - two\n>\n> > nested\n>\n> ```text\n> [!TIP]\n> ```\n> <script>alert(1)</script>";
    const html = render(source);
    expect(render(source, false, true)).not.toContain('role="note"');
    expect(html).toContain("<ul");
    expect(html).toContain("<blockquote");
    expect(html).toContain("[!TIP]");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
    expect(render("```md\n> [!WARNING]\n> literal\n```", true)).not.toContain('role="note"');
  });

  it("reconciles every stream prefix and keeps committed callouts stable", () => {
    const source = "> [!IMPORTANT]\n> first\n>\n> second\n\nAfter.";
    for (let end = 1; end <= source.length; end++) {
      const prefix = source.slice(0, end);
      const segments = buildMarkdownRenderSegments(prefix, true);
      expect(segments.flatMap((segment) => parseBlocks(segment.text))).toEqual(parseBlocks(prefix));
      expect(() => render(prefix, true)).not.toThrow();
    }
    expect(render(source, true)).toContain('role="note"');
    const block = parseBlocks(source)[0];
    expect(blockPropsEqual({ block, live: false }, { block: { ...block }, live: false })).toBe(true);
    expect(blockPropsEqual({ block, live: false }, { block: { type: "callout", kind: "TIP", content: "first\n\nsecond" }, live: false })).toBe(false);
    expect(blockPropsEqual({ block, live: false }, { block: { type: "callout", kind: "IMPORTANT", content: "changed" }, live: false })).toBe(false);
  });

  it("keeps links accessible, labels unique, and pathological nesting bounded", () => {
    const html = render("> [!TIP]\n> [Help](https://example.com)\n\n> [!TIP]\n> Again");
    const ids = [...html.matchAll(/aria-labelledby="([^"]+)"/g)].map((m) => m[1]);
    expect(new Set(ids).size).toBe(2);
    expect(html).toContain('href="https://example.com"');
    const nested = Array.from({ length: 100 }, (_, i) => `${"> ".repeat(i + 1)}[!NOTE]`).join("\n");
    const nestedHtml = render(nested);
    expect(nestedHtml.match(/role="note"/g)).toHaveLength(9);
    expect(nestedHtml).toContain("[!NOTE]");
  });
});
