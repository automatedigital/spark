import { authHeaders, fetchJSON, getApiBase } from "./apiHelpers";

export interface ToolResultPage {
  content: string;
  offset: number;
  next_offset: number | null;
  total_bytes: number;
  truncated: boolean;
  revision: string;
  sha256: string;
}
const resultPath = (sessionId: string, toolId: string) =>
  `/api/sessions/${encodeURIComponent(sessionId)}/tool-results/${encodeURIComponent(toolId)}`;

export function readToolResult(sessionId: string, toolId: string, signal: AbortSignal, page?: ToolResultPage) {
  const query = new URLSearchParams({ paged: "true", offset: String(page?.next_offset ?? 0) });
  if (page) query.set("revision", page.revision);
  return fetchJSON<ToolResultPage>(`${resultPath(sessionId, toolId)}?${query}`, { signal });
}

export async function downloadToolResult(sessionId: string, toolId: string, page: ToolResultPage, signal: AbortSignal) {
  const response = await fetch(`${getApiBase()}${resultPath(sessionId, toolId)}/download?revision=${encodeURIComponent(page.revision)}`, {
    headers: authHeaders(), signal,
  });
  if (!response.ok) throw new Error(`Download failed (${response.status})`);
  const blob = await response.blob();
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", await blob.arrayBuffer())))
    .map((byte) => byte.toString(16).padStart(2, "0")).join("");
  if (blob.size !== page.total_bytes || hash !== page.sha256) throw new Error("Result changed or download incomplete");
  return blob;
}
