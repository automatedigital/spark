/** Explicit, browser-local text prompts. No attachments or context are serialized. */
export const PROMPT_STASH_LIMIT = 20;
export const PROMPT_STASH_TEXT_LIMIT = 16_000;
export interface PromptStashScope { backend: string; profile: string }
export interface SavedPrompt { id: string; text: string; savedAt: number }
export function promptStashKey(scope: PromptStashScope): string {
  return `spark.prompt-stash.v1:${JSON.stringify([scope.backend, scope.profile])}`;
}
export function readPromptStash(scope: PromptStashScope): SavedPrompt[] {
  const raw = localStorage.getItem(promptStashKey(scope));
  if (raw === null) return [];
  if (raw.length > 2_000_000) throw new Error("Saved prompts are invalid; browser storage was not changed.");
  let value;
  try { value = JSON.parse(raw); } catch { throw new Error("Saved prompts are invalid; browser storage was not changed."); }
  if (value?.version !== 1 || !Array.isArray(value.items) || value.items.length > PROMPT_STASH_LIMIT ||
    !value.items.every((item: SavedPrompt) => item && typeof item.id === "string" && item.id.length > 0 && item.id.length <= 100 &&
      typeof item.text === "string" && item.text.trim() && item.text.length <= PROMPT_STASH_TEXT_LIMIT && Number.isFinite(item.savedAt)) ||
    new Set(value.items.map((item: SavedPrompt) => item.id)).size !== value.items.length) {
    throw new Error("Saved prompts are invalid; browser storage was not changed.");
  }
  return value.items.map(({ id, text, savedAt }: SavedPrompt) => ({ id, text, savedAt }));
}
export function savePrompt(scope: PromptStashScope, text: string): SavedPrompt[] {
  if (!text.trim()) throw new Error("Enter prompt text before saving.");
  if (text.length > PROMPT_STASH_TEXT_LIMIT) throw new Error(`Prompts can contain up to ${PROMPT_STASH_TEXT_LIMIT.toLocaleString()} characters.`);
  const items = readPromptStash(scope);
  if (items.length >= PROMPT_STASH_LIMIT) throw new Error(`Saved prompts are full (${PROMPT_STASH_LIMIT}). Delete one before saving.`);
  const next = [{ id: crypto.randomUUID(), text, savedAt: Date.now() }, ...items];
  localStorage.setItem(promptStashKey(scope), JSON.stringify({ version: 1, items: next }));
  return next;
}
export function deletePrompt(scope: PromptStashScope, id: string): SavedPrompt[] {
  const next = readPromptStash(scope).filter((item) => item.id !== id);
  localStorage.setItem(promptStashKey(scope), JSON.stringify({ version: 1, items: next }));
  return next;
}
