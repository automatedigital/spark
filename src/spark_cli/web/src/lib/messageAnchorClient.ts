import { fetchJSON } from "./apiHelpers";
import type { SessionMessage } from "./apiTypes";

export interface MessageWindow {
  session_id: string;
  history_session_id: string;
  lineage: string[];
  anchor_id: number | null;
  anchor_status: "found" | "unavailable";
  notice: string | null;
  messages: SessionMessage[];
  has_earlier: boolean;
  has_newer: boolean;
  before_id: number | null;
  after_id: number | null;
}
export function readMessageWindow(sessionId: string, messageId: string, signal: AbortSignal, direction?: { before_id: number } | { after_id: number }) {
  const query = new URLSearchParams({ limit: "50" });
  if (direction) Object.entries(direction).forEach(([key, value]) => query.set(key, String(value)));
  return fetchJSON<MessageWindow>(`/api/sessions/${encodeURIComponent(sessionId)}/message-window/${encodeURIComponent(messageId)}?${query}`, { signal });
}
