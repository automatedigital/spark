import { describe, expect, it } from "vitest";
import { tokenizeUserBubbleText } from "./userBubbleTokens";

describe("tokenizeUserBubbleText", () => {
  it("links plain http and https URLs", () => {
    expect(tokenizeUserBubbleText("see http://example.com and https://example.com/path")).toEqual([
      { type: "text", text: "see " },
      { type: "link", text: "http://example.com", href: "http://example.com" },
      { type: "text", text: " and " },
      { type: "link", text: "https://example.com/path", href: "https://example.com/path" },
    ]);
  });

  it("links www URLs with an https href", () => {
    expect(tokenizeUserBubbleText("go to www.example.com/docs")).toEqual([
      { type: "text", text: "go to " },
      { type: "link", text: "www.example.com/docs", href: "https://www.example.com/docs" },
    ]);
  });

  it("keeps sentence punctuation outside the URL link", () => {
    expect(tokenizeUserBubbleText("See https://example.com/path?q=1.")).toEqual([
      { type: "text", text: "See " },
      { type: "link", text: "https://example.com/path?q=1", href: "https://example.com/path?q=1" },
      { type: "text", text: "." },
    ]);
  });

  it("keeps surrounding parentheses outside the URL link", () => {
    expect(tokenizeUserBubbleText("(https://example.com).")).toEqual([
      { type: "text", text: "(" },
      { type: "link", text: "https://example.com", href: "https://example.com" },
      { type: "text", text: ")." },
    ]);
  });

  it("preserves balanced parentheses inside URLs", () => {
    expect(tokenizeUserBubbleText("see https://example.com/a(b).")).toEqual([
      { type: "text", text: "see " },
      { type: "link", text: "https://example.com/a(b)", href: "https://example.com/a(b)" },
      { type: "text", text: "." },
    ]);
  });

  it("preserves existing @file highlighting", () => {
    expect(tokenizeUserBubbleText("open @files/foo.ts")).toEqual([
      { type: "text", text: "open " },
      { type: "highlight", text: "@files/foo.ts" },
    ]);
  });

  it("preserves leading slash command highlighting", () => {
    expect(tokenizeUserBubbleText("/model claude")).toEqual([
      { type: "highlight", text: "/model" },
      { type: "text", text: " claude" },
    ]);
  });

  it("links multiple URLs inside mixed text", () => {
    expect(tokenizeUserBubbleText("read https://one.example, then www.two.example/docs")).toEqual([
      { type: "text", text: "read " },
      { type: "link", text: "https://one.example", href: "https://one.example" },
      { type: "text", text: ", then " },
      { type: "link", text: "www.two.example/docs", href: "https://www.two.example/docs" },
    ]);
  });

  it("leaves unsupported or unsafe-looking text plain", () => {
    expect(tokenizeUserBubbleText("javascript:alert(1) file:///tmp/a.txt www.")).toEqual([
      { type: "text", text: "javascript:alert(1) file:///tmp/a.txt www." },
    ]);
  });
});
