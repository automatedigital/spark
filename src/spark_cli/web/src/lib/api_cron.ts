/** cron endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  CronJob,
} from "./apiTypes";

type CronJobFields = {
  prompt: string;
  schedule: string;
  name?: string;
  deliver?: string;
  model?: string | null;
  provider?: string | null;
  skills?: string[];
};

export const cronApi = {
  getCronProviders: () => fetchJSON<{ id: string; label: string }[]>("/api/cron/providers"),
  getCronJobs: () => fetchJSON<CronJob[]>("/api/cron/jobs"),
  createCronJob: (job: CronJobFields) =>
    fetchJSON<CronJob>("/api/cron/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    }),
  updateCronJob: (id: string, updates: Partial<CronJobFields>) =>
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

  // Skills & Toolsets
};
