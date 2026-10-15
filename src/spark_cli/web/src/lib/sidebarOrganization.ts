import type { SessionInfo } from "./apiTypes";
import { DEFAULT_SIDEBAR_METADATA, type SidebarMetadata, type SidebarAttention } from "./api_sidebar";

export type SidebarEntries = Record<string, SidebarMetadata>;
export function mergeSidebarEntries(current: SidebarEntries, incoming: SidebarEntries): SidebarEntries {
  const result = { ...incoming };
  for (const [id, entry] of Object.entries(current)) {
    if (incoming[id] && entry.revision > incoming[id].revision) result[id] = entry;
  }
  return result;
}
export function sidebarStatus(session: SessionInfo, attention?: SidebarAttention, unread = false): string {
  if (attention?.pending_decision) return "Needs you";
  if (session.is_active || attention?.running) return "Running";
  if (attention?.status === "failed") return "Failed";
  if (["interrupted", "cancelled"].includes(attention?.status ?? "")) return "Interrupted";
  return unread ? "Unread" : "Ready";
}
export function isEffectivelySettled(session: SessionInfo, entries: SidebarEntries, attention?: SidebarAttention) {
  return Boolean(entries[session.id]?.settled && !session.is_active && !attention?.running && !attention?.pending_decision);
}
/** Activity remains the default. Once arranged, unpositioned/new rows follow the
 * manual rows in creation order, so token activity can never move arranged work. */
export function orderSidebarSessions(sessions: SessionInfo[], entries: SidebarEntries): SessionInfo[] {
  const manual = sessions.some((s) => entries[s.id]?.position != null);
  return [...sessions].sort((a, b) => manual
    ? ((entries[a.id]?.position ?? Infinity) - (entries[b.id]?.position ?? Infinity)
      || b.started_at - a.started_at || a.id.localeCompare(b.id))
    : b.last_active - a.last_active || b.started_at - a.started_at || a.id.localeCompare(b.id));
}
/** Only the moved row needs a CAS write. Freeze unpositioned neighbors first. */
export function sidebarMovePatches(sessions: SessionInfo[], entries: SidebarEntries, id: string, direction: -1 | 1) {
  const ordered = orderSidebarSessions(sessions, entries);
  const index = ordered.findIndex((s) => s.id === id);
  const target = index + direction;
  if (index < 0 || target < 0 || target >= ordered.length) return [];
  const positions = new Map<string, number>();
  let last = -1024;
  const patches: Array<{ id: string; revision: number; position: number }> = [];
  ordered.forEach((s) => {
    const meta = entries[s.id] ?? DEFAULT_SIDEBAR_METADATA;
    const position = meta.position ?? last + 1024;
    positions.set(s.id, position);
    last = position;
    if (meta.position === null) patches.push({ id: s.id, revision: meta.revision, position });
  });
  ordered.splice(index, 1);
  ordered.splice(target, 0, sessions.find((s) => s.id === id)!);
  const before = ordered[target - 1];
  const after = ordered[target + 1];
  const low = before ? positions.get(before.id)! : positions.get(after.id)! - 2048;
  const high = after ? positions.get(after.id)! : low + 2048;
  const position = (low + high) / 2;
  // Precision exhaustion is rare; never silently collide/rewrite another row.
  if (!(position > low && position < high)) throw new Error("Order is too dense; reset this thread's order first");
  const existing = patches.find((p) => p.id === id);
  if (existing) existing.position = position;
  else patches.push({ id, revision: entries[id]?.revision ?? 0, position });
  return patches;
}
