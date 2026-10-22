import { describe, expect, it } from "vitest";
import { mermaidSourceError } from "./mermaidSafety";
import { blockPropsEqual, buildMarkdownRenderSegments, parseBlocks } from "./markdownParse";

describe("passive Mermaid source policy", () => {
  it.each([
    "flowchart LR\n  A[Start] --> B[Finish]",
    "sequenceDiagram\n  Alice->>Bob: Hello",
    "stateDiagram-v2\n  [*] --> Ready",
    "graph LR\n A <--> B",
    "graph LR\n A[Fetch data from API] --> B[Image processing]",
  ])("accepts ordinary diagram source: %s", (source) => expect(mermaidSourceError(source)).toBeNull());

  it.each([
    'flowchart LR\n A[<img src=x onerror=alert(1)>]',
    'flowchart LR\n A[&lt;script&gt;]',
    'flowchart LR\n click A "javascript:alert(1)"',
    'flowchart LR\n click A callback',
    'flowchart LR\n click\tA\tcallback',
    'flowchart LR\n A@{ img: "https://evil.test/image" }',
    '%%{init: {"securityLevel":"loose"}}%%\n graph LR\n A-->B',
    '---\nconfig:\n securityLevel: loose\n---\ngraph LR\nA-->B',
    'graph LR\nclassDef bad fill:url(https://evil.test)',
    'graph LR\nstyle A fill:red',
    'graph LR\nstyle\tA\tfill:red',
    'graph LR\nlinkStyle 0 stroke:red',
    'graph LR\nA[https://evil.test]',
  ])("rejects active content before import/render: %s", (source) => expect(mermaidSourceError(source)).toContain("unsupported"));

  it("bounds source size and line count, including empty source", () => {
    expect(mermaidSourceError(" ")).toContain("empty");
    expect(mermaidSourceError("x".repeat(8001))).toContain("size limit");
    expect(mermaidSourceError("x\n".repeat(150))).toContain("size limit");
  });
});

// Completion belongs to the parser's actual code nodes, not fences hidden in
// details/literal bodies. Keep the original independent-fence assertions.
const codeBlocks = (text: string) => parseBlocks(text).filter((block) => block.type === "code");
const completionFlags = (text: string) => codeBlocks(text).map((block) => block.closed);

describe("completed fence dispatch", () => {
  const details = (body: string) => `<details>\n<summary>Evidence</summary>\n${body}\n</details>`;
  const ordinary = "```text\nplain\n```";
  const partial = "```mermaid\ngraph LR\nA-->B";

  it.each([
    details(ordinary),
    details(ordinary).replace("<details>", '<details onclick="evil()">'),
    details(details(ordinary)),
    "> [!NOTE]\n> ```text\n> plain\n> ```",
    details("> [!TIP]\n> ```text\n> plain\n> ```"),
  ])("owns completion independently of preceding nested/literal fences: %s", (prefix) => {
    for (const [ending, closed] of [["", false], ["\n```bad", false], ["\n```", true], ["\n``` \t", true]] as const) {
      const blocks = codeBlocks(`${prefix}\n\n${partial}${ending}`);
      expect(blocks).toEqual([{ type: "code", lang: "mermaid", content: "graph LR\nA-->B", closed }]);
    }
  });

  it("retains ordinary code content and malformed-closing parse boundaries", () => {
    expect(parseBlocks("```js\nconst x = 1\n```bad\nafter")).toEqual([
      { type: "code", lang: "js", content: "const x = 1", closed: false },
      { type: "paragraph", content: "after" },
    ]);
  });

  it("updates memo equality when only the owned closing fence changes", () => {
    const block = codeBlocks(partial)[0];
    expect(blockPropsEqual({ block, live: false }, { block: { ...block }, live: false })).toBe(true);
    expect(blockPropsEqual({ block, live: false }, { block: codeBlocks(partial + "\n```")[0], live: false })).toBe(false);
  });

  it("tracks independent fences, including duplicate source and ordinary code", () => {
    expect(completionFlags("```js\nconst x = 1\n```\n```mermaid\ngraph LR\n```\n```mermaid\ngraph LR"))
      .toEqual([true, true, false]);
  });
  it("does not treat a malformed closing line as an eligible closing fence", () => {
    expect(completionFlags("```mermaid\ngraph LR\n```bad")).toEqual([false]);
  });
  it("keeps virtually closed streaming tails ineligible until commit", () => {
    const partial = "```mermaid\ngraph LR\nA-->B";
    const [tail] = buildMarkdownRenderSegments(partial, true);
    expect(tail.live).toBe(true);
    expect(completionFlags(tail.text)).toEqual([true]);
    const [committed] = buildMarkdownRenderSegments(partial, false);
    expect(committed.live).toBe(false);
    expect(completionFlags(committed.text)).toEqual([false]);
  });
});
