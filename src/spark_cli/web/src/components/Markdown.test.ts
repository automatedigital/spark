import { describe, it, expect } from "vitest";
import { parseBlocks, parseInline, findStableBoundary, blockPropsEqual } from "./markdownParse";

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
});

describe("parseBlocks basics", () => {
  it("parses headings, lists, code and paragraphs", () => {
    const blocks = parseBlocks("# Title\n\npara\n\n- one\n- two\n\n```\ncode\n```");
    const types = blocks.map((b) => b.type);
    expect(types).toEqual(["heading", "paragraph", "list", "code"]);
  });
});
