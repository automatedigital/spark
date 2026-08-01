import { describe, expect, it } from "vitest";
import { recordWebEfficiency, snapshotWebEfficiencyMetrics } from "./efficiencyMetrics";

describe("web efficiency metrics", () => {
  it("records count-only values and resets deterministically", () => {
    snapshotWebEfficiencyMetrics(true);
    recordWebEfficiency("httpPolls", 2);
    recordWebEfficiency("eventPayloadBytes", 120);
    expect(snapshotWebEfficiencyMetrics()).toMatchObject({ httpPolls: 2, eventPayloadBytes: 120 });
    expect(snapshotWebEfficiencyMetrics(true).httpPolls).toBe(2);
    expect(snapshotWebEfficiencyMetrics().httpPolls).toBe(0);
  });
});
