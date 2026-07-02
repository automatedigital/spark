import { describe, expect, it } from "vitest";
import {
  estimateAssistantRowSize,
  findLiveRowIndex,
  shouldSkipRowMeasurement,
  type MeasurableRow,
} from "./rowMeasurement";

const row = (role: string, streaming = false): MeasurableRow => ({
  msg: { role, streaming },
});
const typingRow: MeasurableRow = { msg: null };

describe("findLiveRowIndex", () => {
  it("returns the last streaming assistant row", () => {
    const items = [row("user"), row("assistant"), row("tool"), row("assistant", true)];
    expect(findLiveRowIndex(items)).toBe(3);
  });

  it("returns -1 when nothing is streaming", () => {
    expect(findLiveRowIndex([row("user"), row("assistant")])).toBe(-1);
    expect(findLiveRowIndex([])).toBe(-1);
  });

  it("ignores streaming flags on non-assistant rows", () => {
    expect(findLiveRowIndex([row("user", true), row("assistant")])).toBe(-1);
  });
});

describe("shouldSkipRowMeasurement", () => {
  const items = [row("user"), row("assistant"), row("tool"), row("assistant", true)];
  const liveIndex = findLiveRowIndex(items);

  it("skips only the live streaming row mid-stream", () => {
    expect(shouldSkipRowMeasurement(items[3], 3, liveIndex, false)).toBe(true);
    // Committed assistant rows must be measured even while a turn streams.
    expect(shouldSkipRowMeasurement(items[1], 1, liveIndex, false)).toBe(false);
    expect(shouldSkipRowMeasurement(items[0], 0, liveIndex, false)).toBe(false);
    expect(shouldSkipRowMeasurement(items[2], 2, liveIndex, false)).toBe(false);
  });

  it("measures everything once no row is live", () => {
    const idle = [row("user"), row("assistant")];
    expect(shouldSkipRowMeasurement(idle[1], 1, findLiveRowIndex(idle), false)).toBe(false);
  });

  it("keeps safe-mode tool/reasoning skips", () => {
    expect(shouldSkipRowMeasurement(row("tool"), 0, -1, true)).toBe(true);
    expect(shouldSkipRowMeasurement(row("reasoning"), 0, -1, true)).toBe(true);
    expect(shouldSkipRowMeasurement(row("assistant"), 0, -1, true)).toBe(false);
  });

  it("never skips the typing indicator or missing rows", () => {
    expect(shouldSkipRowMeasurement(typingRow, 0, 0, false)).toBe(false);
    expect(shouldSkipRowMeasurement(undefined, 0, 0, false)).toBe(false);
  });
});

describe("estimateAssistantRowSize", () => {
  it("is uncapped at 900px for long content", () => {
    expect(estimateAssistantRowSize("x".repeat(20_000))).toBeGreaterThan(900);
  });

  it("adds height for fenced code blocks", () => {
    const prose = "hello world ".repeat(40);
    const withFence = `${prose}\n\`\`\`ts\nconst a = 1;\n\`\`\``;
    expect(estimateAssistantRowSize(withFence)).toBeGreaterThan(estimateAssistantRowSize(prose));
  });

  it("keeps a sane floor and ceiling", () => {
    expect(estimateAssistantRowSize("")).toBe(96);
    expect(estimateAssistantRowSize("x".repeat(2_000_000))).toBe(20_000);
  });
});
