import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { formatTurnDuration, type TurnTimingSummary } from "./turnTiming";
import { TurnTimingDetails } from "../components/chat/TurnTimingDetails";
import { SessionInfoBar } from "../components/chat/SessionInfoBar";

const timing: TurnTimingSummary = { version: 1, clock: "server_monotonic", accepted: true,
  seconds: { queue: 0.125, finish: 2 }, tool_count: 0, usage: null };

describe("turn timing disclosure", () => {
  it("keeps unknown, negative and nonfinite spans honest", () => {
    for (const value of [null, undefined, -1, Infinity, NaN]) expect(formatTurnDuration(value)).toBe("Unknown");
    expect(formatTurnDuration(0)).toBe("0.000 s");
    const html = renderToStaticMarkup(createElement(TurnTimingDetails, { timing }));
    expect(html).toContain("0.125 s");
    expect(html).toContain("2.000 s");
    expect(html).toContain("Provider start to first text token");
    expect(html).toContain("Unknown");
    expect(html).toContain("Browser display delay is separate");
  });
  it("is quiet by default even when stats and usage are absent", () => {
    const html = renderToStaticMarkup(createElement(SessionInfoBar, { stats: {}, timing }));
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("Turn details");
    expect(html).not.toContain("Preparation after acceptance");
  });
});
