import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ToolCallBubble } from "./ToolCallBubble";

describe("ToolCallBubble", () => {
  it("renders elapsed tool time from server timestamps in seconds", () => {
    const html = renderToStaticMarkup(createElement(ToolCallBubble, {
      name: "web_search",
      args: { query: "slow search" },
      result: "{}",
      done: true,
      startedAt: 1000,
      endedAt: 1125,
    }));

    expect(html).toContain("125.0s");
    expect(html).not.toContain("0.1s");
  });

  it("prefers explicit server duration when present", () => {
    const html = renderToStaticMarkup(createElement(ToolCallBubble, {
      name: "web_extract",
      args: { urls: ["https://example.com"] },
      result: "{}",
      done: true,
      startedAt: 1000,
      endedAt: 1000.2,
      durationSeconds: 183.42,
    }));

    expect(html).toContain("183.4s");
    expect(html).not.toContain("0.2s");
  });
});
