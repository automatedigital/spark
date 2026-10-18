import { readFileSync } from "node:fs";
import ts from "typescript";
import { describe, expect, it, vi } from "vitest";

// Execute the actual search and bookmark effect callbacks with a deterministic
// RAF queue. No product-only test export or duplicate restoration algorithm.
// The browser diagnostic separately verifies real DOM/virtualizer behavior.
const sourceText = readFileSync(new URL("./ChatPanel.tsx", import.meta.url), "utf8");
const source = ts.createSourceFile("ChatPanel.tsx", sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

function findCallback(marker: string, hook = "useEffect"): ts.Expression {
  let found: ts.Expression | undefined;
  function visit(node: ts.Node) {
    if (ts.isCallExpression(node) && node.expression.getText(source) === hook
      && node.arguments[0]?.getText(source).includes(marker)) {
      if (found) throw new Error(`Ambiguous callback: ${marker}`);
      found = node.arguments[0];
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  if (!found) throw new Error(`Missing callback: ${marker}`);
  return found;
}

function compile<T>(callback: ts.Expression, scope: Record<string, unknown>): T {
  const { outputText } = ts.transpileModule(`return (${callback.getText(source)});`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
  });
  return new Function(...Object.keys(scope), outputText)(...Object.values(scope)) as T;
}

const searchCallback = findCallback("if (!searchMatches.length) return;");
const bookmarkCallback = findCallback("const saved = pendingThreadScroll.current;");
const lookupCallback = findCallback("let turnIndex = 0;", "useCallback");
type Effect = () => void | (() => void);

function fixture({ matches = [251], safeMode = false } = {}) {
  const frames: FrameRequestCallback[] = [];
  const prependRestoreGenerationRef = { current: 64 };
  const pendingThreadScroll = {
    current: { sessionId: "cached", top: 0, anchorId: "turn:user:db:551", offset: 20 } as {
      sessionId: string; top: number; anchorId: string; offset: number;
    } | null,
  };
  const restoringThreadScroll = { current: true };
  let top = 0;
  const writes: number[] = [];
  const element = {
    get scrollTop() { return top; },
    set scrollTop(value: number) { top = value; writes.push(value); },
    querySelector: () => null,
    getBoundingClientRect: () => ({ top: 0 }),
  };
  const chatMessages = Array.from({ length: 300 }, (_, index) => ({
    id: `db:${2251 + index}`, role: index % 2 ? "assistant" : "user",
  }));
  const turnIndexForMessageIndex = compile<(index: number) => number>(lookupCallback, { chatMessages });
  const scrollToIndex = vi.fn<(index: number, options: { align: string; behavior: string }) => void>(() => {
    element.scrollTop = 16_495;
  });
  const scope = {
    searchMatches: matches, searchMatchIdx: 0, turnIndexForMessageIndex, safeMode,
    virtualizer: { scrollToIndex }, prependRestoreGenerationRef, pendingThreadScroll, restoringThreadScroll,
    activeSessionId: "cached", loadingHistory: false,
    timelineTurnsRef: { current: chatMessages.filter(message => message.role === "user").map(message => ({ id: `turn:user:${message.id}` })) },
    scrollContainerRef: { current: element },
    requestAnimationFrame: (callback: FrameRequestCallback) => { frames.push(callback); return frames.length; },
    cancelAnimationFrame: vi.fn(),
    CSS: { escape: (value: string) => value },
  };
  return {
    scope, writes, element, frames, scrollToIndex,
    search: () => compile<Effect>(searchCallback, scope)(),
    bookmark: () => compile<Effect>(bookmarkCallback, scope)(),
    frame: () => { const callback = frames.shift(); if (!callback) throw new Error("Missing scheduled RAF"); callback(0); },
  };
}

describe("ChatPanel explicit search ownership", () => {
  it("fences an already queued missing-anchor bookmark before issuing the smooth search", () => {
    const f = fixture();
    f.bookmark();
    expect(f.frames).toHaveLength(1);
    f.scrollToIndex.mockImplementation((index, options) => {
      expect(index).toBe(125); // cached message 251 belongs to user db:2501
      expect(options).toEqual({ align: "center", behavior: "smooth" });
      expect(f.scope.prependRestoreGenerationRef.current).toBe(65);
      expect(f.scope.pendingThreadScroll.current).toBeNull();
      expect(f.scope.restoringThreadScroll.current).toBe(false);
      f.element.scrollTop = 16_495;
    });
    f.search();
    f.frame();
    expect(f.writes).toEqual([16_495]);
    expect(f.frames).toHaveLength(0);
  });

  it("retains bookmark restoration when search has no matches", () => {
    const f = fixture({ matches: [] });
    f.bookmark();
    const saved = f.scope.pendingThreadScroll.current;
    f.search();
    expect(f.scrollToIndex).not.toHaveBeenCalled();
    expect(f.scope.prependRestoreGenerationRef.current).toBe(64);
    expect(f.scope.pendingThreadScroll.current).toBe(saved);
    expect(f.scope.restoringThreadScroll.current).toBe(true);
    f.frame();
    expect(f.writes).toEqual([0]);
    expect(f.frames).toHaveLength(1);
  });

  it("retires each prior restore across next-match navigation and preserves safe-mode behavior", () => {
    const f = fixture({ matches: [251, 1], safeMode: true });
    f.bookmark();
    f.search();
    f.scope.searchMatchIdx = 1;
    f.search();
    f.frame();
    expect(f.scrollToIndex.mock.calls).toEqual([
      [125, { align: "center", behavior: "instant" }],
      [0, { align: "center", behavior: "instant" }],
    ]);
    expect(f.scope.prependRestoreGenerationRef.current).toBe(66);
    expect(f.writes).toEqual([16_495, 16_495]);
  });

  it("does not let an old RAF clear a later session's pending bookmark", () => {
    const f = fixture();
    f.bookmark();
    f.search();
    const replacement = { sessionId: "replacement", top: 100, anchorId: "new-anchor", offset: 0 };
    f.scope.pendingThreadScroll.current = replacement;
    f.scope.restoringThreadScroll.current = true;
    f.frame();
    expect(f.scope.pendingThreadScroll.current).toBe(replacement);
    expect(f.scope.restoringThreadScroll.current).toBe(true);
    expect(f.writes).toEqual([16_495]);
  });
});
