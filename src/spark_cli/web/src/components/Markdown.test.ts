import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Markdown } from "./Markdown";
import {
  parseBlocks,
  parseInline,
  findStableBoundary,
  blockPropsEqual,
  buildMarkdownRenderSegments,
} from "./markdownParse";

/**
 * The streaming renderer splits a message into a stable committed prefix and a
 * live tail using findStableBoundary, then parses each independently. This MUST
 * be equivalent to parsing the whole string — otherwise committed blocks would
 * render differently than the final message. These cases lock that invariant,
 * especially around fenced code blocks (the only construct spanning blank lines).
 */
describe("findStableBoundary + parseBlocks incremental equivalence", () => {
  const cases: string[] = [
    "",
    "single paragraph with no blank lines",
    "para one\n\npara two\n\npartial tail being streamed",
    "# Heading\n\nBody text\n\n- a\n- b\n\ntail",
    // Fenced code containing a blank line — boundary must not split inside it.
    "intro\n\n```js\nconst a = 1;\n\nconst b = 2;\n```\n\nafter the code\n\ntail",
    // Unclosed (still-streaming) fence — everything from the fence on is the tail.
    "intro paragraph\n\n```python\ndef f():\n    return 1\n\ndef g():",
    // A table followed by more content.
    "| a | b |\n|---|---|\n| 1 | 2 |\n\nfollowing paragraph\n\ntail",
    // Multiple code blocks.
    "```\nfirst\n```\n\nmiddle\n\n```\nsecond\n```\n\nend",
    "trailing blank lines\n\n\n\n",
  ];

  for (const [i, content] of cases.entries()) {
    it(`case ${i} splits without changing the parse`, () => {
      const boundary = findStableBoundary(content);
      expect(boundary).toBeGreaterThanOrEqual(0);
      expect(boundary).toBeLessThanOrEqual(content.length);

      const stable = content.slice(0, boundary);
      const tail = content.slice(boundary);
      const split = [...parseBlocks(stable), ...parseBlocks(tail)];
      const whole = parseBlocks(content);
      expect(split).toEqual(whole);
    });
  }

  it("never places the boundary inside an open code fence", () => {
    const content = "before\n\n```js\nline1\n\nline2";
    const boundary = findStableBoundary(content);
    // The fence starts after "before\n\n"; the boundary must be at or before it.
    expect(boundary).toBeLessThanOrEqual("before\n\n".length);
  });
});

describe("parseInline hardening (no catastrophic backtracking)", () => {
  it("handles adversarial MEDIA: input in linear time", () => {
    // Inputs shaped to trigger the old nested-quantifier backtracking. The
    // rewritten linear regex must complete near-instantly.
    const inputs = [
      "MEDIA: /" + "a/".repeat(4000) + " no-extension-here",
      "MEDIA: " + "word ".repeat(4000) + "!",
      "MEDIA: /path/" + "x ".repeat(4000) + ".notmedia",
    ];
    for (const input of inputs) {
      const start = Date.now();
      const nodes = parseInline(input);
      const elapsed = Date.now() - start;
      expect(Array.isArray(nodes)).toBe(true);
      expect(elapsed).toBeLessThan(100);
    }
  });

  it("still parses ordinary inline markup", () => {
    const nodes = parseInline("see **bold**, `code`, and [a link](https://example.com)");
    const types = nodes.map((n) => n.type);
    expect(types).toContain("bold");
    expect(types).toContain("code");
    expect(types).toContain("link");
  });

  it("still recognizes a real MEDIA: image path", () => {
    const nodes = parseInline("MEDIA: /tmp/shot.png");
    expect(nodes.some((n) => n.type === "media")).toBe(true);
  });
});

describe("streaming markdown parser regression coverage", () => {
  it("preserves ordered-list numbering across blank-line-separated items", () => {
    const blocks = parseBlocks("1. first\n\n2. second\n\n10. tenth");

    expect(blocks).toEqual([
      { type: "list", ordered: true, items: ["first"], start: 1 },
      { type: "list", ordered: true, items: ["second"], start: 2 },
      { type: "list", ordered: true, items: ["tenth"], start: 10 },
    ]);
  });

  it("parses the screenshot shape as markdown blocks while content is still streaming", () => {
    const content = [
      "## Heading",
      "",
      "### 1. Subheading",
      "",
      "A paragraph with **bold** text.",
      "",
      "- first bullet",
      "- second bullet",
      "",
      "streamed tail appended after a blank line",
    ].join("\n");
    const boundary = findStableBoundary(content);
    const blocks = [
      ...parseBlocks(content.slice(0, boundary)),
      ...parseBlocks(content.slice(boundary)),
    ];

    expect(blocks).toEqual([
      { type: "heading", level: 2, content: "Heading" },
      { type: "heading", level: 3, content: "1. Subheading" },
      { type: "paragraph", content: "A paragraph with **bold** text." },
      { type: "list", ordered: false, items: ["first bullet", "second bullet"] },
      { type: "paragraph", content: "streamed tail appended after a blank line" },
    ]);
    const paragraph = blocks.find((block) => block.type === "paragraph" && block.content.includes("**bold**"));
    expect(paragraph?.type).toBe("paragraph");
    if (paragraph?.type === "paragraph") {
      expect(parseInline(paragraph.content)).toContainEqual({ type: "bold", content: "bold" });
    }
  });

  it("keeps partial streaming constructs safe and lets them settle to the final parse", () => {
    const partials = [
      "##",
      "## Partial heading",
      "**partial bold",
      "[partial link](https://example.com",
      "```ts\nconst x = 1;",
      "- partial list item",
      "> partial quote",
      "| a | b |\n|---|---|",
    ];

    for (const partial of partials) {
      expect(() => parseBlocks(partial)).not.toThrow();
      expect(() => parseInline(partial)).not.toThrow();
    }

    expect(parseBlocks("## Partial heading")).toEqual([
      { type: "heading", level: 2, content: "Partial heading" },
    ]);
    expect(parseInline("**partial bold**")).toContainEqual({ type: "bold", content: "partial bold" });
    expect(parseInline("[partial link](https://example.com)")).toContainEqual({
      type: "link",
      text: "partial link",
      href: "https://example.com",
    });
  });

  it("treats pipe-prefixed ASCII diagrams as paragraphs instead of hanging", () => {
    const content = [
      "+--------------------------------------+",
      "| Experience & Edge Layer              |",
      "| CDN | WAF | API Gateway | Auth Proxy |",
      "+--------------------------------------+",
      "",
      "tail",
    ].join("\n");
    const start = Date.now();
    const blocks = parseBlocks(content);

    expect(Date.now() - start).toBeLessThan(100);
    expect(blocks).toEqual([
      {
        type: "paragraph",
        content: [
          "+--------------------------------------+",
          "| Experience & Edge Layer              |",
          "| CDN | WAF | API Gateway | Auth Proxy |",
          "+--------------------------------------+",
        ].join("\n"),
      },
      { type: "paragraph", content: "tail" },
    ]);
  });
});

describe("Markdown component streaming behavior", () => {
  it("renders active streams as markdown, not plain text", () => {
    const html = renderToStaticMarkup(createElement(Markdown, {
      content: "## Heading\n\nA **bold** line.\n\n- one",
      streaming: true,
    }));

    expect(html).toContain("<h2");
    expect(html).toContain("<strong");
    expect(html).toContain("<ul");
    expect(html).not.toContain("## Heading");
  });

  it("keeps safe mode plain even while streaming", () => {
    const html = renderToStaticMarkup(createElement(Markdown, {
      content: "## Heading\n\nA **bold** line.",
      streaming: true,
      safeMode: true,
    }));

    expect(html).not.toContain("<h2");
    expect(html).not.toContain("<strong");
    expect(html).toContain("## Heading");
    expect(html).toContain("**bold**");
  });

  it("renders long active streams incrementally as markdown", () => {
    const content = [
      "# Older heading",
      "",
      "older stable text\n\n".repeat(500),
      "## Fresh tail",
      "",
      "A **bold** live tail.",
    ].join("\n");
    const html = renderToStaticMarkup(createElement(Markdown, {
      content,
      streaming: true,
    }));

    expect(html).toContain("<h1");
    expect(html).toContain("<h2");
    expect(html).toContain("<strong");
    expect(html).toContain("older stable text");
    expect(html).not.toContain("## Fresh tail");
  });

  it("bounds per-flush parse cost to the live tail for long responses", () => {
    const content = [
      "# Head",
      "",
      "streaming paragraph\n\n".repeat(180),
      "## Live tail",
      "",
      "A **bold** live tail.",
    ].join("\n");
    const segments = buildMarkdownRenderSegments(content, true);
    const liveSegments = segments.filter((segment) => segment.live);
    const liveChars = liveSegments.reduce((sum, s) => sum + s.text.length, 0);

    expect(content.length).toBeGreaterThan(3_000);
    // Exactly one live segment re-parses per flush; everything else is
    // committed markdown whose stable keys keep memoized renders intact.
    expect(liveSegments).toHaveLength(1);
    expect(liveChars).toBeLessThanOrEqual(6_000);
    // Committed + live reassemble the full content (no fences here, so the
    // stabilized live text is the raw tail).
    expect(segments.map((s) => s.text).join("")).toBe(content);
  });

  it("keeps committed segment keys prefix-stable as the stream grows", () => {
    const base = [
      "# Head",
      "",
      "committed paragraph\n\n".repeat(300),
    ].join("\n");
    const before = buildMarkdownRenderSegments(`${base}partial tail`, true);
    const after = buildMarkdownRenderSegments(`${base}partial tail grew **longer**`, true);

    const committedBefore = before.filter((s) => !s.live);
    const committedAfter = after.filter((s) => !s.live);
    expect(committedAfter.length).toBe(committedBefore.length);
    committedBefore.forEach((seg, i) => {
      expect(committedAfter[i].start).toBe(seg.start);
      expect(committedAfter[i].end).toBe(seg.end);
      expect(committedAfter[i].text).toBe(seg.text);
    });
  });

  it("virtually closes an open fence in the live tail", () => {
    const content = "intro\n\n```python\ndef f():\n    return 1";
    const segments = buildMarkdownRenderSegments(content, true);
    const live = segments.find((s) => s.live);
    expect(live).toBeDefined();
    expect(live!.text.endsWith("\n```")).toBe(true);
    // Offsets still describe the real content, not the stabilized text.
    expect(live!.end).toBe(content.length);

    const html = renderToStaticMarkup(createElement(Markdown, {
      content,
      streaming: true,
    }));
    expect(html).toContain("def f()");
    expect(html).toContain("<pre");
  });

  it("falls back to the windowed plain tail for very large streams", () => {
    const content = `# Head\n\n${"huge paragraph\n\n".repeat(2_000)}live tail`;
    expect(content.length).toBeGreaterThan(20_000);
    const segments = buildMarkdownRenderSegments(content, true);
    expect(segments.some((segment) => segment.kind === "plain" && segment.live)).toBe(true);
  });

  it("renders large completed markdown in chunks instead of falling back to raw text", () => {
    const content = [
      "# Older heading",
      "",
      "stable paragraph\n\n".repeat(500),
      "## Final heading",
      "",
      "A **bold** final tail.",
    ].join("\n");
    const html = renderToStaticMarkup(createElement(Markdown, {
      content,
      streaming: false,
    }));

    expect(html).toContain("<h1");
    expect(html).toContain("<h2");
    expect(html).toContain("<strong");
    expect(html).not.toContain("## Final heading");
  });

  it("renders completed markdown richly when under the soft cap", () => {
    const html = renderToStaticMarkup(createElement(Markdown, {
      content: "## Done\n\nA **bold** final answer.\n\n```bash\necho ok\n```",
      streaming: false,
    }));

    expect(html).toContain("<h2");
    expect(html).toContain("<strong");
    expect(html).toContain("Copy code");
    expect(html).not.toContain("## Done");
  });

  it("initializes code and table wrap controls from the global default", () => {
    const content = [
      "```ts",
      "const value = 'a very long line that should wrap when enabled';",
      "```",
      "",
      "| Header | Another header |",
      "|---|---|",
      "| a very long cell value | another very long cell value |",
    ].join("\n");
    const html = renderToStaticMarkup(createElement(Markdown, {
      content,
      defaultWrap: true,
    }));

    expect(html).toContain('aria-label="Disable code word wrap"');
    expect(html).toContain('aria-label="Disable table word wrap"');
    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("whitespace-pre-wrap");
    expect(html).toContain("table-fixed");
  });

  it("keeps code and table overflow scrolling by default", () => {
    const content = [
      "```",
      "long line",
      "```",
      "",
      "| Header |",
      "|---|",
      "| cell |",
    ].join("\n");
    const html = renderToStaticMarkup(createElement(Markdown, { content }));

    expect(html).toContain('aria-label="Enable code word wrap"');
    expect(html).toContain('aria-label="Enable table word wrap"');
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain("overflow-x-auto");
  });

  it("defers syntax highlighting for live code and enables it after completion", () => {
    const content = "```js\nconst x = 1;\n```";
    const live = renderToStaticMarkup(createElement(Markdown, { content, streaming: true }));
    const done = renderToStaticMarkup(createElement(Markdown, { content, streaming: false }));

    expect(live).not.toContain("hljs-keyword");
    expect(done).toContain("hljs-keyword");
  });

  it("renders local markdown file paths in code spans as openable file buttons", () => {
    const html = renderToStaticMarkup(createElement(Markdown, {
      content: "Created the report here: `/Users/joe/.spark/workspace/current-best-llm-report.md`",
      streaming: false,
    }));

    expect(html).toContain("<button");
    expect(html).toContain("current-best-llm-report.md");
    expect(html).toContain("Open raw file");
    expect(html).toContain("Open in Files");
    expect(html).not.toContain("<code");
  });

  it("renders local markdown file paths in plain text as openable file buttons", () => {
    const html = renderToStaticMarkup(createElement(Markdown, {
      content: "Report saved at /Users/joe/.spark/workspace/current-best-llm-report.md.",
      streaming: false,
    }));

    expect(html).toContain("<button");
    expect(html).toContain("current-best-llm-report.md");
    expect(html).toContain("Open in Files");
    expect(html).toContain("Report saved at ");
  });

  it("renders large streaming tables live with row truncation", () => {
    const content = [
      "| a | b |",
      "|---|---|",
      ...Array.from({ length: 120 }, (_, i) => `| ${i} | ${i + 1} |`),
    ].join("\n");
    const html = renderToStaticMarkup(createElement(Markdown, {
      content,
      streaming: true,
    }));

    expect(html).toContain("<table");
    expect(html).toContain("Showing first 80 rows while streaming.");
    expect(html).not.toContain(">119<");
  });
});

describe("markdown parser malformed and large input coverage", () => {
  it("handles unclosed fences, huge paragraphs, huge tables, task lists, and malformed links", () => {
    const hugeParagraph = "word ".repeat(20_000);
    expect(() => parseBlocks(hugeParagraph)).not.toThrow();
    expect(parseBlocks("- [ ] todo\n- [x] done")).toEqual([
      { type: "list", ordered: false, items: ["[ ] todo", "[x] done"] },
    ]);

    const table = [
      "| a | b | c |",
      "|---|---|---|",
      ...Array.from({ length: 300 }, (_, i) => `| ${i} | ${i + 1} | ${i + 2} |`),
    ].join("\n");
    const [tableBlock] = parseBlocks(table);
    expect(tableBlock.type).toBe("table");
    if (tableBlock.type === "table") expect(tableBlock.rows).toHaveLength(300);

    expect(() => parseBlocks("```bash\necho still open")).not.toThrow();
    expect(() => parseInline("[broken](https://example.com")).not.toThrow();
    expect(() => parseInline("***".repeat(5000) + "text")).not.toThrow();
    expect(parseInline("https://example.com/a(b).")).toContainEqual({
      type: "link",
      text: "https://example.com/a(b)",
      href: "https://example.com/a(b)",
    });
  });
});

describe("parseInline links", () => {
  it("parses markdown links and bare URLs into link nodes", () => {
    expect(parseInline("[docs](https://example.com/path?q=1#frag)")).toEqual([
      { type: "link", text: "docs", href: "https://example.com/path?q=1#frag" },
    ]);
    expect(parseInline("visit https://example.com/path?q=1#frag")).toEqual([
      { type: "text", content: "visit " },
      { type: "link", text: "https://example.com/path?q=1#frag", href: "https://example.com/path?q=1#frag" },
    ]);
  });

  it("keeps trailing punctuation outside bare URL hrefs", () => {
    expect(parseInline("See https://example.com/path?q=1#frag.")).toEqual([
      { type: "text", content: "See " },
      { type: "link", text: "https://example.com/path?q=1#frag", href: "https://example.com/path?q=1#frag" },
      { type: "text", content: "." },
    ]);
    expect(parseInline("(https://example.com/a(b)).")).toEqual([
      { type: "text", content: "(" },
      { type: "link", text: "https://example.com/a(b)", href: "https://example.com/a(b)" },
      { type: "text", content: ")." },
    ]);
  });

  it("supports parenthesized URLs inside markdown links", () => {
    expect(parseInline("[example](https://example.com/a(b)?q=1#frag)")).toEqual([
      { type: "link", text: "example", href: "https://example.com/a(b)?q=1#frag" },
    ]);
  });
});

/**
 * The freeze fix relies on MemoBlock skipping re-render for every committed block
 * as the streaming tail grows. blockPropsEqual is the exact comparator React uses;
 * these tests simulate token-by-token growth and assert that already-committed
 * blocks compare equal (skip) while only the changing tail block compares unequal.
 */
describe("blockPropsEqual drives committed-block skip during streaming", () => {
  it("reports committed blocks as unchanged while only the tail block changes", () => {
    const base = "# Title\n\nFirst paragraph that is already complete.\n\n";
    const tailSteps = ["The", "The tail", "The tail paragraph", "The tail paragraph grows."];

    let prevBlocks: ReturnType<typeof parseBlocks> | null = null;
    let committedSkips = 0;
    let tailChanges = 0;

    for (const step of tailSteps) {
      const blocks = parseBlocks(base + step);
      if (prevBlocks) {
        // All blocks except the last are committed; they must compare equal.
        for (let i = 0; i < blocks.length - 1; i++) {
          const equal = blockPropsEqual(
            { block: prevBlocks[i], live: false },
            { block: blocks[i], live: false },
          );
          expect(equal).toBe(true);
          committedSkips++;
        }
        // The tail block changed between steps → must compare unequal.
        const lastPrev = prevBlocks[prevBlocks.length - 1];
        const lastNext = blocks[blocks.length - 1];
        expect(blockPropsEqual({ block: lastPrev, live: true }, { block: lastNext, live: true })).toBe(false);
        tailChanges++;
      }
      prevBlocks = blocks;
    }

    expect(committedSkips).toBeGreaterThan(0);
    expect(tailChanges).toBe(tailSteps.length - 1);
  });

  it("treats a block as changed when its live flag flips (code highlight on completion)", () => {
    const [block] = parseBlocks("```js\nconst x = 1;\n```");
    expect(blockPropsEqual({ block, live: true }, { block, live: false })).toBe(false);
  });

  it("treats a block as changed when safe mode flips", () => {
    const [block] = parseBlocks("MEDIA: /tmp/shot.png");
    expect(blockPropsEqual({ block, live: false, safeMode: false }, { block, live: false, safeMode: true })).toBe(false);
  });
});

/**
 * Characterizes the core property behind the fix: per-frame parse work depends on
 * the size of the live tail, not the (potentially huge) committed prefix. Without
 * the split, parseBlocks ran over the whole growing message every frame — O(n²)
 * over a stream. Thresholds are generous to stay non-flaky on slow CI.
 */
describe("streaming parse cost is bounded by the tail, not the whole message", () => {
  it("parses only the small tail regardless of prefix size", () => {
    const bigPrefix = "para block with some text.\n\n".repeat(2000); // ~56k chars, ~2000 blocks
    const tail = "the response is still being written";
    const content = bigPrefix + tail;

    const boundary = findStableBoundary(content);
    const tailPart = content.slice(boundary);
    // The live tail is just the in-progress region, not the whole message.
    expect(tailPart.length).toBeLessThan(200);

    const start = Date.now();
    for (let i = 0; i < 60; i++) parseBlocks(tailPart); // ~one second of frames
    const perFrame = (Date.now() - start) / 60;
    expect(perFrame).toBeLessThan(2); // sub-2ms/frame for tail parse
  });

  it("keeps parse work bounded for 10k, 50k, and 100k character streams", () => {
    for (const size of [10_000, 50_000, 100_000]) {
      const prefix = "stable paragraph\n\n".repeat(Math.ceil(size / "stable paragraph\n\n".length)).slice(0, size);
      const content = `${prefix}\n\nlive tail still growing`;
      const boundary = findStableBoundary(content);
      const tailPart = content.slice(boundary);

      expect(tailPart.length).toBeLessThan(200);
      const start = Date.now();
      for (let i = 0; i < 60; i++) parseBlocks(tailPart);
      const perFrame = (Date.now() - start) / 60;
      expect(perFrame).toBeLessThan(2);
    }
  });

  it("segments huge open streaming blocks into a markdown head plus plain live tail", () => {
    const content = "one very long open paragraph ".repeat(5_000);
    const segments = buildMarkdownRenderSegments(content, true, {
      liveTailSize: 2_000,
      streamingHeadSize: 1_000,
      streamingFullSize: 3_000,
    });
    const livePlain = segments.filter((segment) => segment.kind === "plain" && segment.live);
    const notice = segments.find((segment) => segment.kind === "plain" && !segment.live);
    const markdown = segments.filter((segment) => segment.kind === "markdown");

    expect(markdown).toHaveLength(1);
    expect(notice?.text).toContain("showing the live tail");
    expect(livePlain).toHaveLength(1);
    expect(livePlain[0].text.length).toBeLessThanOrEqual(2_000);
    expect(markdown[0].text).toBe(content.slice(0, 1_000));
    expect(livePlain[0].text).toBe(content.slice(-2_000));
  });

  it("splits stable markdown on safe boundaries so old chunks stay memoizable", () => {
    const content = Array.from({ length: 180 }, (_, i) => `## Section ${i}\n\nBody ${i}.`).join("\n\n");
    const segments = buildMarkdownRenderSegments(content, false, {
      chunkTargetSize: 500,
      chunkMaxSize: 900,
    });

    expect(segments.length).toBeGreaterThan(3);
    expect(segments.every((segment) => segment.kind === "markdown" && !segment.live)).toBe(true);
    expect(segments.map((segment) => segment.text).join("")).toBe(content);
  });

  it("does not hide content when segmenting very large completed markdown", () => {
    const content = [
      "# Head",
      "",
      "middle paragraph\n\n".repeat(6_000),
      "## Tail",
      "",
      "A **bold** tail.",
    ].join("\n");
    const segments = buildMarkdownRenderSegments(content, false, {
      chunkTargetSize: 1_000,
      chunkMaxSize: 1_500,
    });

    expect(segments.length).toBeGreaterThan(2);
    expect(segments.every((segment) => segment.kind === "markdown" && !segment.live)).toBe(true);
    expect(segments.map((segment) => segment.text).join("")).toBe(content);
    expect(segments.some((segment) => segment.text.includes("hidden for render performance"))).toBe(false);
  });

  it("renders oversized completed messages as full plain text instead of hiding content", () => {
    const content = [
      "# Head",
      "",
      "middle paragraph\n\n".repeat(6_000),
      "## Tail",
    ].join("\n");

    const html = renderToStaticMarkup(createElement(Markdown, { content }));

    expect(html).toContain("# Head");
    expect(html).toContain("middle paragraph");
    expect(html).toContain("## Tail");
    expect(html).not.toContain("hidden for render performance");
    expect(html).not.toContain("<h1");
  });
});

describe("parseBlocks basics", () => {
  it("parses headings, lists, code and paragraphs", () => {
    const blocks = parseBlocks("# Title\n\npara\n\n- one\n- two\n\n```\ncode\n```");
    const types = blocks.map((b) => b.type);
    expect(types).toEqual(["heading", "paragraph", "list", "code"]);
  });
});
