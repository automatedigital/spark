import { flushDraft, getDraft, updateDraft } from "./draftStore";

/** Text-only recall from the loaded transcript; contextItems are never restored. */
export interface ComposerPromptHistoryEntry {
  id: string;
  prompt: string;
}

export function buildComposerPromptHistoryEntries(
  messages: readonly { id: string; role: string; content?: string }[],
): ComposerPromptHistoryEntry[] {
  const seen = new Set<string>();
  return messages.flatMap((message) => {
    if (message.role !== "user" || !message.content?.trim() || seen.has(message.id)) return [];
    seen.add(message.id);
    return [{ id: message.id, prompt: message.content }];
  });
}

export interface ComposerPromptHistoryBrowse {
  owner: string;
  entries: readonly ComposerPromptHistoryEntry[];
  index: number;
  draft: string;
}

/** Snapshot the list so new/earlier messages cannot move the selected prompt. */
export function recallComposerPrompt(
  owner: string,
  entries: readonly ComposerPromptHistoryEntry[],
  index: number,
  draft: string,
): ComposerPromptHistoryBrowse | null {
  return entries[index] ? { owner, entries: [...entries], index, draft } : null;
}

export function stepComposerPromptHistory(
  owner: string,
  browse: ComposerPromptHistoryBrowse | null,
  entries: readonly ComposerPromptHistoryEntry[],
  input: string,
  direction: "backward" | "forward",
): { browse: ComposerPromptHistoryBrowse | null; prompt: string } | null {
  const active = browse?.owner === owner ? browse : null;
  if (!active) {
    if (direction !== "backward" || input !== "") return null;
    const next = recallComposerPrompt(owner, entries, entries.length - 1, input);
    return next ? { browse: next, prompt: next.entries[next.index].prompt } : null;
  }
  const index = active.index + (direction === "backward" ? -1 : 1);
  if (index < 0) return null;
  if (index >= active.entries.length) return { browse: null, prompt: active.draft };
  return { browse: { ...active, index }, prompt: active.entries[index].prompt };
}

/** Strict boundaries preserve ordinary movement in multiline and wrapped text. */
export function canNavigateComposerHistory(input: {
  key: string; text: string; start: number; end: number;
  menuOpen: boolean; modified: boolean; composing: boolean;
}): boolean {
  if (input.menuOpen || input.modified || input.composing || input.start !== input.end) return false;
  return (input.key === "ArrowUp" && input.start === 0)
    || (input.key === "ArrowDown" && input.end === input.text.length);
}

/** A recovery slot uses the existing draft store (including its conflict and
 * write-failure handling), under the captured backend/profile/project/thread.
 * JSON distinguishes an original empty string from an unused recovery slot.
 * It is deliberately not acknowledged when the recalled prompt is submitted.
 */
export const composerRecoveryKey = (scopeKey: string) => `${scopeKey}:composer-history`;
export function readComposerRecovery(scopeKey: string): string | null {
  const raw = getDraft(composerRecoveryKey(scopeKey)).draft.text;
  if (!raw) return null;
  try { const text: unknown = JSON.parse(raw); return typeof text === "string" ? text : null; }
  catch { return null; }
}
export function saveComposerRecovery(scopeKey: string, text: string): boolean {
  const key = composerRecoveryKey(scopeKey);
  const entry = getDraft(key);
  if (entry.status === "conflict" || entry.status === "unavailable"
    || entry.draft.text && readComposerRecovery(scopeKey) === null) return false;
  updateDraft(key, { text: JSON.stringify(text) });
  flushDraft(key);
  return getDraft(key).status === "saved";
}
