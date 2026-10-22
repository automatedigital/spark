import { beforeEach, expect, it, vi } from "vitest";
import { deletePrompt, PROMPT_STASH_LIMIT, PROMPT_STASH_TEXT_LIMIT, promptStashKey, readPromptStash, savePrompt } from "./promptStashStore";
const scope = { backend: "http://fixture", profile: "/synthetic/profile-a" };
let values: Map<string, string>;
beforeEach(() => {
  values = new Map();
  vi.stubGlobal("localStorage", { getItem: (k: string) => values.get(k) ?? null, setItem: (k: string, v: string) => values.set(k, v) });
});
it("round-trips exact Unicode/multiline text and deletes without capturing context", () => {
  const text = "  reusable\n你好 🚀  ";
  const [item] = savePrompt(scope, text);
  expect(readPromptStash(scope)).toEqual([item]);
  expect(item.text).toBe(text);
  expect(Object.keys(item).sort()).toEqual(["id", "savedAt", "text"]);
  expect(deletePrompt(scope, item.id)).toEqual([]);
  expect(readPromptStash(scope)).toEqual([]);
});
it("isolates backend/profile but shares between threads and projects", () => {
  savePrompt(scope, "private");
  expect(readPromptStash({ ...scope, profile: "/synthetic/profile-b" })).toEqual([]);
  expect(readPromptStash({ ...scope, backend: "http://other" })).toEqual([]);
  expect(promptStashKey({ backend: "a,b", profile: "c" })).not.toBe(promptStashKey({ backend: "a", profile: "b,c" }));
});
it("rejects blank, oversized, and full stash without evicting saved text", () => {
  expect(() => savePrompt(scope, " \n")).toThrow();
  expect(() => savePrompt(scope, "x".repeat(PROMPT_STASH_TEXT_LIMIT + 1))).toThrow();
  savePrompt(scope, "x".repeat(PROMPT_STASH_TEXT_LIMIT));
  for (let n = 1; n < PROMPT_STASH_LIMIT; n++) savePrompt(scope, String(n));
  const before = values.get(promptStashKey(scope));
  expect(() => savePrompt(scope, "overflow")).toThrow(/full/);
  expect(values.get(promptStashKey(scope))).toBe(before);
});
it.each(["broken", '{"version":2,"items":[]}', '{"version":1,"items":[{"id":"a","text":4}]}', '{"version":1,"items":null}'])("preserves invalid/versioned storage: %s", (raw) => {
  values.set(promptStashKey(scope), raw);
  expect(() => readPromptStash(scope)).toThrow(/invalid/);
  expect(() => savePrompt(scope, "new")).toThrow();
  expect(() => deletePrompt(scope, "a")).toThrow();
  expect(values.get(promptStashKey(scope))).toBe(raw);
});
it("propagates denied read and quota/delete failure without claiming persistence", () => {
  const [item] = savePrompt(scope, "existing");
  const before = values.get(promptStashKey(scope));
  vi.stubGlobal("localStorage", { getItem: () => before, setItem: () => { throw new Error("quota"); } });
  expect(() => savePrompt(scope, "new")).toThrow("quota");
  expect(() => deletePrompt(scope, item.id)).toThrow("quota");
  expect(values.get(promptStashKey(scope))).toBe(before);
  vi.stubGlobal("localStorage", { getItem: () => { throw new Error("denied"); } });
  expect(() => readPromptStash(scope)).toThrow("denied");
});
