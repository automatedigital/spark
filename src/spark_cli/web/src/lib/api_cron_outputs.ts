import { fetchJSON } from "./apiHelpers";

export interface SavedOutputPage { files: string[]; next_before: string | null }
export interface SavedOutput { filename: string; content: string; truncated: boolean; max_bytes: number }
const path = (id: string) => `/api/cron/jobs/${encodeURIComponent(id)}/outputs`;
export const savedOutputsApi = {
  list: (id: string, before?: string) => fetchJSON<SavedOutputPage>(`${path(id)}?limit=20${before ? `&before=${encodeURIComponent(before)}` : ""}`),
  read: (id: string, filename: string) => fetchJSON<SavedOutput>(`${path(id)}/${encodeURIComponent(filename)}`),
};
