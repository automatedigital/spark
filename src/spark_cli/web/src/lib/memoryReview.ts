import { apiConnectionGeneration, fetchJSON } from "./apiHelpers";
import { sidebarPreferenceScopeGeneration } from "./sidebarPrefs";

async function read<T>(url: string, init?: RequestInit): Promise<T> {
  const connection = apiConnectionGeneration();
  const profile = sidebarPreferenceScopeGeneration();
  const result = await fetchJSON<T>(url, init);
  if (init?.signal?.aborted || connection !== apiConnectionGeneration() || profile !== sidebarPreferenceScopeGeneration()) {
    throw new DOMException("Memory request scope changed", "AbortError");
  }
  return result;
}

export interface MemoryTarget {
  target: string; entries: string[]; entry_count: number; chars: number; limit: number; percent: number;
}
export interface Fact {
  fact_id: number; content: string; content_truncated: 0 | 1; source: string | null; category: string | null;
  created_at: string | null; updated_at: string | null;
}
export interface FactPage {
  status: "available" | "missing" | "unavailable"; items: Fact[]; next_after: number | null; message?: string;
}
export interface ReviewPage {
  status: "available" | "missing" | "unavailable"; items: { name: string }[]; next_after?: string | null;
}
export const memoryReview = {
  targets: (signal?: AbortSignal) => read<{ targets: Record<string, MemoryTarget> }>("/api/memory", { signal }),
  mutate: (target: string, action: "entry" | "replace", body: object, method = "POST") =>
    read<MemoryTarget>(`/api/memory/${encodeURIComponent(target)}/${action}`, {
      method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }),
  facts: (q: string, after: number, signal: AbortSignal) => read<FactPage>(`/api/memory/facts?${new URLSearchParams({ q, after: String(after) })}`, { signal }),
  fact: (id: number, signal: AbortSignal) => read<FactPage>(`/api/memory/facts/${id}`, { signal }),
  reviews: (after: string, signal: AbortSignal) => read<ReviewPage>(`/api/memory/reviews?${new URLSearchParams({ after })}`, { signal }),
  review: (name: string, signal: AbortSignal) => read<{ name: string; content: string }>(`/api/memory/reviews/${encodeURIComponent(name)}`, { signal }),
};
