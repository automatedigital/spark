import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { contextModeSummary, contextPressureLevel, formatContextTokens } from "./contextWindowPolicy";
import { ContextWindowMeter } from "./ContextWindowMeter";
import type { ContextItem } from "@/lib/context";

const item = (id: string, inclusion_mode: ContextItem["inclusion_mode"]): ContextItem => ({
  id,
  type: "file",
  inclusion_mode,
  scope: "one_turn",
  size_bytes: 10,
});

describe("ContextWindowMeter policy helpers", () => {
  it("labels pressure at the warning and critical thresholds", () => {
    expect(contextPressureLevel(0.79)).toBe("normal");
    expect(contextPressureLevel(0.8)).toBe("warning");
    expect(contextPressureLevel(0.95)).toBe("critical");
  });

  it("reports explicit summarized and reduced context", () => {
    expect(contextModeSummary([
      item("a", "full"),
      item("b", "summary"),
      item("c", "excerpt"),
      item("d", "path_only"),
    ])).toEqual(["1 summarized", "2 reduced"]);
  });

  it("formats compact estimates", () => {
    expect(formatContextTokens(900)).toBe("900");
    expect(formatContextTokens(12_400)).toBe("12K");
    expect(formatContextTokens(1_200_000)).toBe("1.2M");
  });

  it("exposes a labelled disclosure trigger for the dismissible details dialog", () => {
    const html = renderToStaticMarkup(createElement(ContextWindowMeter, {
      estimate: {
        prompt_tokens: 100,
        attached_tokens: 20,
        pinned_tokens: 0,
        history_tokens: 80,
        total_tokens: 200,
        context_window: 1000,
        utilization: 0.2,
        warning: null,
        buckets: [],
      },
      loading: false,
    }));

    expect(html).toContain('aria-haspopup="dialog"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toMatch(/aria-controls="context-window-[^"]+"/);
  });
});
