import { describe, expect, it } from "vitest";
import { buildMarkdownRenderSegments, parseBlocks, parseInline } from "./markdownParse";

function alphaResponse(count = 80): string {
  return `${Array.from({ length: count }, (_, i) => `ALPHA-${String(i + 1).padStart(2, "0")}`).join(" ")} DONE-ALPHA`;
}

describe("completed streamed markdown content", () => {
  it("keeps hyphenated token streams intact after the turn completes", () => {
    const content = alphaResponse();
    const segments = buildMarkdownRenderSegments(content, false);
    expect(segments.map((segment) => segment.text).join("")).toBe(content);

    const blocks = parseBlocks(segments[0].text);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ type: "paragraph", content });

    const inlineText = parseInline(content)
      .map((node) => {
        switch (node.type) {
          case "text":
            return node.content;
          case "code":
          case "bold":
          case "italic":
          case "strike":
            return node.content;
          case "link":
            return node.text;
          case "media":
            return node.path;
          case "br":
            return "\n";
        }
      })
      .join("");
    expect(inlineText).toBe(content);
  });
});
