import { describe, expect, it } from "vitest";
import { contextModeSummary, contextPressureLevel, formatContextTokens } from "./contextWindowPolicy";
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
});
