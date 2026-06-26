import type { CronJob } from "../api";
import type { FetchJSON } from "./model";

export interface CronJobCreate {
  prompt: string;
  schedule: string;
  name?: string;
  deliver?: string;
}

export interface CronJobUpdate {
  prompt?: string;
  schedule?: string;
  name?: string;
  deliver?: string;
}

export function createCronApi(fetchJSON: FetchJSON) {
  return {
    getCronJobs: () => fetchJSON<CronJob[]>("/api/cron/jobs"),
    createCronJob: (job: CronJobCreate) =>
      fetchJSON<CronJob>("/api/cron/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(job),
      }),
    updateCronJob: (id: string, updates: CronJobUpdate) =>
      fetchJSON<CronJob>(`/api/cron/jobs/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updates }),
      }),
    pauseCronJob: (id: string) =>
      fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/pause`, { method: "POST" }),
    resumeCronJob: (id: string) =>
      fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/resume`, { method: "POST" }),
    triggerCronJob: (id: string) =>
      fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}/trigger`, { method: "POST" }),
    deleteCronJob: (id: string) =>
      fetchJSON<{ ok: boolean }>(`/api/cron/jobs/${id}`, { method: "DELETE" }),
  };
}

export type CronApi = ReturnType<typeof createCronApi>;
