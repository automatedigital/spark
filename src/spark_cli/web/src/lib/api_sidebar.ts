import { authHeaders, getApiBase } from "./apiHelpers";

export interface SidebarMetadata {
  pinned: boolean;
  settled: boolean;
  position: number | null;
  revision: number;
}
export interface SidebarAttention {
  running: boolean;
  pending_decision: boolean;
  status: string | null;
}
export interface SidebarSnapshot {
  schema_version: 1;
  entries: Record<string, SidebarMetadata>;
  attention?: Record<string, SidebarAttention>;
  preference_scope: string;
}
export const DEFAULT_SIDEBAR_METADATA: SidebarMetadata = { pinned: false, settled: false, position: null, revision: 0 };
export class SidebarMutationError extends Error {
  current?: SidebarMetadata;
  constructor(message: string, current?: SidebarMetadata) { super(message); this.current = current; }
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBase()}/api/sidebar/threads${path}`, {
    ...init, headers: authHeaders(init?.headers),
  });
  const data = await response.json().catch(() => null);
  if (!data || typeof data !== "object") throw new SidebarMutationError("Thread organization is unavailable; refresh after reconnecting");
  if (!response.ok) throw new SidebarMutationError(
    typeof data.detail === "string" ? data.detail : "Could not update thread organization", data.current,
  );
  return data;
}
export const sidebarApi = {
  getSidebarThreads: () => request<SidebarSnapshot>(""),
  patchSidebarThread: (id: string, expected_revision: number, fields: Partial<Omit<SidebarMetadata, "revision">>) =>
    request<{ schema_version: 1; session_id: string; metadata: SidebarMetadata }>(`/${encodeURIComponent(id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision, ...fields }),
    }),
};
