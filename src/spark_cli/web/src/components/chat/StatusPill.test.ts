import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MODEL_LOADING_LABEL, StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("uses one stable model-loading label while streaming without status text", () => {
    const html = renderToStaticMarkup(createElement(StatusPill, { streaming: true }));

    expect(html).toContain(MODEL_LOADING_LABEL);
    expect(html).toContain("data-state=\"model-loading\"");
    expect(html).toContain("spark-status-shimmer");
    expect(html).not.toContain("Thinking");
    expect(html).not.toContain("Reasoning");
  });

  it("normalizes legacy provider-wait copy to the stable model-loading label", () => {
    const html = renderToStaticMarkup(createElement(StatusPill, {
      streaming: true,
      label: "Waiting for provider response…",
    }));

    expect(html).toContain(MODEL_LOADING_LABEL);
    expect(html).not.toContain("Waiting for provider response");
  });

  it("normalizes elapsed provider-wait messages from backend lifecycle events", () => {
    const html = renderToStaticMarkup(createElement(StatusPill, {
      streaming: true,
      label: "Waiting for provider response (10s elapsed). Timeout in about 50s.",
    }));

    expect(html).toContain(MODEL_LOADING_LABEL);
    expect(html).not.toContain("10s elapsed");
  });

  it("normalizes calling-model status before provider wait begins", () => {
    const html = renderToStaticMarkup(createElement(StatusPill, {
      streaming: true,
      label: "Calling model…",
    }));

    expect(html).toContain(MODEL_LOADING_LABEL);
    expect(html).not.toContain("Calling model");
  });

  it("keeps tool and reconnect labels distinct", () => {
    const toolHtml = renderToStaticMarkup(createElement(StatusPill, {
      streaming: true,
      label: "Tool: terminal",
    }));
    const reconnectHtml = renderToStaticMarkup(createElement(StatusPill, {
      streaming: true,
      label: "Reconnecting…",
    }));

    expect(toolHtml).toContain("Tool: terminal");
    expect(toolHtml).not.toContain(MODEL_LOADING_LABEL);
    expect(reconnectHtml).toContain("Reconnecting…");
    expect(reconnectHtml).not.toContain(MODEL_LOADING_LABEL);
  });
});
