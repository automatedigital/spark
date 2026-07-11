import { describe, expect, it } from "vitest";
import { CRON_REFRESH_INTERVAL_MS, shouldRefreshCronJobs } from "./cronRefresh";

describe("cron schedule reconciliation", () => {
  it("refreshes on a bounded interval while visible", () => {
    expect(CRON_REFRESH_INTERVAL_MS).toBe(15_000);
    expect(shouldRefreshCronJobs("visible")).toBe(true);
  });

  it("does not poll hidden pages and refreshes when visibility returns", () => {
    expect(shouldRefreshCronJobs("hidden")).toBe(false);
    expect(shouldRefreshCronJobs("visible")).toBe(true);
  });
});
