import type { ContextItem } from "./context";
import { restoreAttachment } from "./attachmentStaging";

export const DRAFT_VERSION = 1;
const PREFIX = "spark.draft.v1";
export interface DraftScope {
  backend: string;
  profile: string;
  project?: string | null;
  thread?: string | null;
}
export interface ChatDraft {
  version: 1;
  text: string;
  contextItems: ContextItem[];
  revision: string;
  updatedAt: number;
}
export type DraftStatus = "idle" | "saving" | "saved" | "recovered" | "unavailable" | "conflict";
export interface DraftEntry {
  draft: ChatDraft;
  status: DraftStatus;
  baseRevision: string | null;
  dirty: boolean;
}
const records = new Map<string, DraftEntry>();
const timers = new Map<string, ReturnType<typeof setTimeout>>();
const listeners = new Set<() => void>();
let sequence = 0;
const writer = Math.random().toString(36).slice(2);
const emit = () => { for (const listener of listeners) listener(); };
const revision = () => `${writer}-${Date.now()}-${++sequence}`;
const empty = (): ChatDraft => ({ version: 1, text: "", contextItems: [], revision: revision(), updatedAt: Date.now() });

export function draftKey(scope: DraftScope): string {
  // JSON encodes null distinctly from literal project/thread names.
  return `${PREFIX}:${JSON.stringify([scope.backend, scope.profile, scope.project ?? null, scope.thread ?? null])}`;
}
function readStored(key: string): ChatDraft | null {
  const value: unknown = JSON.parse(localStorage.getItem(key) || "null");
  if (!value || typeof value !== "object") return null;
  const draft = value as Partial<ChatDraft>;
  if (draft.version !== 1 || typeof draft.text !== "string" || typeof draft.revision !== "string" || !Array.isArray(draft.contextItems)) return null;
  // Corrupt storage must not crash the composer during recovery.
  const valid = draft.contextItems.every((item) => item && typeof item.id === "string" && typeof item.type === "string" && typeof item.inclusion_mode === "string" && typeof item.scope === "string");
  if (!valid) return null;
  return { ...draft, contextItems: draft.contextItems.map(restoreAttachment) } as ChatDraft;
}
export function getDraft(key: string): DraftEntry {
  const existing = records.get(key);
  if (existing) return existing;
  let stored: ChatDraft | null = null;
  let unavailable = false;
  try { stored = readStored(key); } catch { unavailable = true; }
  const entry: DraftEntry = { draft: stored ?? empty(), status: unavailable ? "unavailable" : stored && (stored.text || stored.contextItems.length) ? "recovered" : "idle", baseRevision: stored?.revision ?? null, dirty: false };
  records.set(key, entry);
  return entry;
}
export function flushDraft(key: string): void {
  clearTimeout(timers.get(key));
  timers.delete(key);
  const current = getDraft(key);
  if (!current.dirty || current.status === "conflict") return;
  try {
    const stored = readStored(key);
    if ((stored?.revision ?? null) !== current.baseRevision) {
      records.set(key, { ...current, status: "conflict" });
    } else {
      localStorage.setItem(key, JSON.stringify(current.draft));
      records.set(key, { ...current, baseRevision: current.draft.revision, dirty: false, status: current.draft.text || current.draft.contextItems.length ? "saved" : "idle" });
    }
  } catch {
    records.set(key, { ...current, status: "unavailable" });
  }
  emit();
}
export function updateDraft(key: string, patch: Partial<Pick<ChatDraft, "text" | "contextItems">>): void {
  const current = getDraft(key);
  const next = { ...current.draft, ...patch, revision: revision(), updatedAt: Date.now() };
  records.set(key, { ...current, draft: next, dirty: true, status: current.status === "conflict" ? "conflict" : "saving" });
  clearTimeout(timers.get(key));
  timers.set(key, setTimeout(() => flushDraft(key), 350));
  emit();
}
/** Acknowledgement is scoped to the exact submission, even if the user edits identical text again. */
export function acknowledgeDraft(key: string, submittedRevision: string): boolean {
  const current = getDraft(key);
  if (current.draft.revision !== submittedRevision || current.status === "conflict") return false;
  // Keep pinned context in the next draft; consume only acknowledged one-turn context.
  updateDraft(key, { text: "", contextItems: current.draft.contextItems.filter((item) => item.scope === "pinned") });
  flushDraft(key);
  return true;
}
export function resolveDraftConflict(key: string, choice: "mine" | "stored"): void {
  const current = getDraft(key);
  try {
    const stored = readStored(key);
    records.set(key, choice === "stored"
      ? { draft: stored ?? empty(), status: stored ? "recovered" : "idle", dirty: false, baseRevision: stored?.revision ?? null }
      : { ...current, status: "saving", dirty: true, baseRevision: stored?.revision ?? null });
    if (choice === "mine") flushDraft(key);
    emit();
  } catch {
    records.set(key, { ...current, status: "unavailable" });
    emit();
  }
}
export function discardDraft(key: string): void {
  // Discard the local copy; don't erase another tab's unresolved edits.
  if (getDraft(key).status === "conflict") return;
  updateDraft(key, { text: "", contextItems: [] });
  flushDraft(key);
}
export function subscribeDraft(listener: () => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function receiveDraftStorage(key: string): void {
  const current = records.get(key);
  if (!current) return;
  try {
    const stored = readStored(key);
    if ((stored?.revision ?? null) !== current.baseRevision) {
      records.set(key, { ...current, status: "conflict" });
      emit();
    }
  } catch { /* The in-memory draft remains available. */ }
}
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key?.startsWith(PREFIX)) receiveDraftStorage(event.key);
  });
  window.addEventListener("pagehide", () => { for (const key of records.keys()) flushDraft(key); });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") for (const key of records.keys()) flushDraft(key);
  });
}
