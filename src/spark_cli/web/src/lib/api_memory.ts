/** memory endpoints, split out of api.ts. */

import {
  fetchJSON,
} from "./apiHelpers";
import type {
  MemoryListResponse,
  MemoryTargetPayload,
} from "./apiTypes";

export const memoryApi = {
  getMemory: () => fetchJSON<MemoryListResponse>(`/api/memory`),
  addMemoryEntry: (target: string, content: string) =>
    fetchJSON<MemoryTargetPayload>(`/api/memory/${encodeURIComponent(target)}/entry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }),
  replaceMemoryEntry: (target: string, oldText: string, newContent: string) =>
    fetchJSON<MemoryTargetPayload>(`/api/memory/${encodeURIComponent(target)}/replace`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_text: oldText, new_content: newContent }),
    }),
  removeMemoryEntry: (target: string, oldText: string) =>
    fetchJSON<MemoryTargetPayload>(`/api/memory/${encodeURIComponent(target)}/entry`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_text: oldText }),
    }),
};
