import { describe, expect, it } from "vitest";
import { createCronApi } from "./cron";
import type { FetchJSON } from "./model";

function recorder() {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchJSON = (async <T>(url: string, init?: RequestInit): Promise<T> => {
    calls.push({ url, init });
    return {} as T;
  }) satisfies FetchJSON;
  return { api: createCronApi(fetchJSON), calls };
}

describe("cron api client", () => {
  it("keeps cron endpoints on their existing paths", async () => {
    const { api, calls } = recorder();

    await api.getCronJobs();
    await api.pauseCronJob("job 1");
    await api.resumeCronJob("job 1");
    await api.triggerCronJob("job 1");
    await api.deleteCronJob("job 1");

    expect(calls).toEqual([
      { url: "/api/cron/jobs", init: undefined },
      { url: "/api/cron/jobs/job 1/pause", init: { method: "POST" } },
      { url: "/api/cron/jobs/job 1/resume", init: { method: "POST" } },
      { url: "/api/cron/jobs/job 1/trigger", init: { method: "POST" } },
      { url: "/api/cron/jobs/job 1", init: { method: "DELETE" } },
    ]);
  });

  it("preserves cron create and update JSON bodies", async () => {
    const { api, calls } = recorder();

    await api.createCronJob({ prompt: "ship", schedule: "daily", name: "Daily" });
    await api.updateCronJob("job 1", { schedule: "weekly" });

    expect(calls).toEqual([
      {
        url: "/api/cron/jobs",
        init: {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: "ship", schedule: "daily", name: "Daily" }),
        },
      },
      {
        url: "/api/cron/jobs/job 1",
        init: {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ updates: { schedule: "weekly" } }),
        },
      },
    ]);
  });
});
