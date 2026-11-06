/** cron endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  CronJob,
} from "./apiTypes";

export type CronScheduleJob = Omit<CronJob, "schedule"> & {
  schedule: { kind: string; expr?: string; display?: string; run_at?: string; minutes?: number; timezone?: string };
  paused_reason?: string | null;
};

export type CronJobFields = {
  timezone?: string | null;
  prompt: string;
  schedule: string;
  name?: string;
  deliver?: string;
  model?: string | null;
  provider?: string | null;
  skills?: string[];
};

export type CronSchedulePreview = {
  occurrences: string[];
  timezone: string;
  missed_run_policy: string;
  dst_policy: string;
  readiness: { provider: string | null; model: string | null; delivery_available: boolean;
    skills: { id: string; available: boolean }[]; errors: string[]; verification: string };
};

export const cronApi = {
  previewCronSchedule: (value: Omit<CronJobFields, "prompt">, signal?: AbortSignal) =>
    fetchJSON<CronSchedulePreview>("/api/cron/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(value), signal,
    }),
  getCronSkills: () => fetchJSON<{ id: string; name: string; enabled: boolean; reason?: string }[]>("/api/cron/skills"),
  getCronOutputCapability: () => fetchJSON<{ supported: boolean; reason: string | null }>("/api/cron/output-capability"),
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
