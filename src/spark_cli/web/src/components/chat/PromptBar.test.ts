import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { renderMirror } from "./PromptBar";

describe("PromptBar mirror caret", () => {
  it("places the caret inside an @ token at the actual cursor offset", () => {
    const html = renderToStaticMarkup(renderMirror("use @README.md now", 7, true));

    expect(html).toContain("use ");
    expect(html).toMatch(/<mark[^>]*>@RE<span[^>]*class="prompt-cursor/);
    expect(html).toContain("ADME.md</mark>");
  });

  it("places the caret inside a slash token at the actual cursor offset", () => {
    const html = renderToStaticMarkup(renderMirror("run /search now", 8, true));

    expect(html).toMatch(/<mark[^>]*>\/sea<span[^>]*class="prompt-cursor/);
    expect(html).toContain("ch</mark>");
  });
});
