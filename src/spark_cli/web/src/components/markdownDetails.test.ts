import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";
import { blockPropsEqual, buildMarkdownRenderSegments, findStableBoundary, parseBlocks } from "./markdownParse";

const details = (body = "Supporting **evidence**.", open = false) =>
  `<details${open ? " open" : ""}>\n<summary>Evidence & reasoning</summary>\n${body}\n</details>`;
const render = (content: string, props = {}) => renderToStaticMarkup(createElement(Markdown, { content, ...props }));

describe("safe Markdown details", () => {
  it("recognizes the closed and open grammar, including adjacent paragraphs", () => {
    for (const open of [false, true]) {
      expect(parseBlocks(`before\n${details("body", open)}\nafter`)).toEqual([
        { type: "paragraph", content: "before" },
        { type: "details", summary: "Evidence & reasoning", content: "body", open },
        { type: "paragraph", content: "after" },
      ]);
      const html = render(details("body", open));
      expect(html).toContain(open ? '<details open=""' : '<details class=');
      expect(html).toContain("<summary");
      expect(html).toContain("Evidence &amp; reasoning");
    }
  });

  it("renders body Markdown and copyable fences without treating fenced tags as delimiters", () => {
    const body = '**bold**\n\n```html\n</details>\n<summary>literal code</summary>\n<details onclick="evil()">\n```';
    expect(parseBlocks(details(body))[0]).toMatchObject({ type: "details", content: body });
    const html = render(details(body));
    expect(html).toContain("<strong");
    expect(html).toContain("Copy code");
    expect(html).not.toContain('<details onclick=');
  });

  it.each([
    '<details onclick="evil()">\n<summary>Title</summary>\nbody\n</details>',
    '<details open="true">\n<summary>Title</summary>\nbody\n</details>',
    '<details>\nbody\n</details>',
    '<details>\n<summary onclick="evil()">Title</summary>\nbody\n</details>',
    '<details>\n<summary><img src=x onerror=evil()></summary>\nbody\n</details>',
    details('<summary>second</summary>'),
    details(details()),
    details("body").replace('</details>', ''),
    details("x".repeat(6_001)),
  ])("keeps malformed, nested or oversized input entirely literal: %s", (content) => {
    expect(parseBlocks(content)).toEqual([{ type: "literal", content }]);
    expect(render(content)).not.toContain("<details");
    expect(render(content)).not.toContain("<img");
  });

  it("keeps escaped and fenced tags literal", () => {
    expect(render(`\\${details()}`)).not.toContain("<details");
    expect(render('```html\n' + details() + '\n```')).not.toContain("<details");
    expect(render('&lt;details&gt;\n&lt;summary&gt;Title&lt;/summary&gt;')).not.toContain("<details");
  });

  it("never promotes an unfinished streamed candidate or synthesizes its source", () => {
    const source = details('**bold**\n\n```html\n</details>\n```');
    for (let end = 1; end < source.length; end++) {
      const prefix = source.slice(0, end);
      const segments = buildMarkdownRenderSegments(prefix, true);
      expect(segments.map((s) => s.text).join("")).toBe(prefix);
      expect(render(prefix, { streaming: true })).not.toContain("<details");
    }
    expect(render(source, { streaming: true })).toContain("<details");
  });

  it("keeps blank lines within details out of stable segment boundaries", () => {
    const content = `intro\n\n${details('paragraph\n\n'.repeat(250))}`;
    expect(findStableBoundary(content)).toBe(7);
    for (const streaming of [false, true]) {
      const segments = buildMarkdownRenderSegments(content, streaming);
      expect(segments.map((s) => s.text).join("")).toBe(content);
      expect(segments.flatMap((s) => parseBlocks(s.text)).filter((b) => b.type === "details")).toHaveLength(1);
    }
    expect(findStableBoundary(content + '\n\ntail')).toBe(content.length + 2);
  });

  it("uses plain safe-mode and large-response fallbacks", () => {
    expect(render(details(), { safeMode: true })).not.toContain("<details");
    expect(render(details() + 'x'.repeat(20_001))).not.toContain("<details");
    const segments = buildMarkdownRenderSegments(details('x'.repeat(20_001)), true);
    expect(segments.filter((s) => s.live).every((s) => s.kind === "plain")).toBe(true);
  });

  it("memoizes equal details and detects summary, body and default-open changes", () => {
    const block = parseBlocks(details())[0];
    const props = { block, live: false };
    expect(blockPropsEqual(props, { ...props, block: { ...block } })).toBe(true);
    for (const content of [details('changed'), details(undefined, true), details().replace('Evidence & reasoning', 'Changed')]) {
      expect(blockPropsEqual(props, { ...props, block: parseBlocks(content)[0] })).toBe(false);
    }
  });
});
