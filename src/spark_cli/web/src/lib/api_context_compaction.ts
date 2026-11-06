import { fetchJSON } from "./apiHelpers";

export interface ContextPreflight {
  session_id: string;
  revision: string;
  can_compact: boolean;
  blocked_reason: string | null;
  head_messages: number;
  tail_messages: number;
  summary_messages: number;
  summary_timeout_seconds: number;
  summary_output_tokens: number;
  policy: string;
}
export interface ContextCompactionResult {
  session_id: string;
  parent_session_id?: string;
  status: "compacted" | "unchanged";
  reason?: string;
  before_estimated_tokens: number;
  after_estimated_tokens: number;
  provider_actual_tokens?: number | null;
  elapsed_seconds?: number;
}
const path = (id: string) => `/api/conversations/${encodeURIComponent(id)}/context`;
export const contextCompactionApi = {
  preflight: (id: string, signal?: AbortSignal) => fetchJSON<ContextPreflight>(`${path(id)}/preflight`, { signal }),
  compact: (id: string, revision: string) => fetchJSON<ContextCompactionResult>(`${path(id)}/compact`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ expected_revision: revision }),
  }),
};
