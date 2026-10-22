import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { composerRecoveryKey, readComposerRecovery, saveComposerRecovery } from "./composerPromptHistory";
import { acknowledgeDraft, draftKey, flushDraft, getDraft, receiveDraftStorage, updateDraft } from "./draftStore";

let values: Map<string, string>;
let serial = 0;
const owner = (profile = "p", backend = "local", thread = "A") => draftKey({ backend, profile, thread: `${thread}-${serial}` });
beforeEach(() => {
  serial++;
  values = new Map();
  vi.useFakeTimers();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  });
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("composer recovery through the existing draft store", () => {
  it("persists original and edited recall independently across module reload", async () => {
    const key = owner();
    expect(saveComposerRecovery(key, "original\nΩ")).toBe(true);
    updateDraft(key, { text: "edited recall" }); flushDraft(key);
    vi.resetModules();
    const reloaded = await import("./composerPromptHistory");
    const store = await import("./draftStore");
    expect(reloaded.readComposerRecovery(key)).toBe("original\nΩ");
    expect(store.getDraft(key).draft.text).toBe("edited recall");
  });
  it("keeps original on successful submission and does not consume later edits", () => {
    const key = owner();
    saveComposerRecovery(key, "original");
    updateDraft(key, { text: "recall" }); flushDraft(key);
    const submitted = getDraft(key).draft.revision;
    updateDraft(key, { text: "newer edit" });
    expect(acknowledgeDraft(key, submitted)).toBe(false);
    expect(getDraft(key).draft.text).toBe("newer edit");
    expect(acknowledgeDraft(key, getDraft(key).draft.revision)).toBe(true);
    expect(readComposerRecovery(key)).toBe("original");
  });
  it("isolates backend, profile and thread; captured recovery never writes replacement owner", () => {
    const key = owner(), other = owner("p", "local", "B");
    updateDraft(other, { text: "B private" });
    saveComposerRecovery(key, "A private");
    expect(readComposerRecovery(other)).toBeNull();
    expect(readComposerRecovery(owner("other-profile"))).toBeNull();
    expect(readComposerRecovery(owner("p", "other-backend"))).toBeNull();
    expect(getDraft(other).draft.text).toBe("B private");
  });
  it("distinguishes empty originals and swaps edited text without losing either", () => {
    const key = owner();
    expect(readComposerRecovery(key)).toBeNull();
    saveComposerRecovery(key, "");
    expect(readComposerRecovery(key)).toBe("");
    const original = readComposerRecovery(key)!;
    saveComposerRecovery(key, "edited recall");
    updateDraft(key, { text: original });
    expect(getDraft(key).draft.text).toBe("");
    expect(readComposerRecovery(key)).toBe("edited recall");
  });
  it("refuses quota failure, storage conflicts and malformed recovery", () => {
    const key = owner();
    vi.spyOn(localStorage, "setItem").mockImplementationOnce(() => { throw new Error("quota"); });
    expect(saveComposerRecovery(key, "original")).toBe(false);
    const conflict = owner("conflict");
    saveComposerRecovery(conflict, "original");
    values.set(composerRecoveryKey(conflict), JSON.stringify({ ...getDraft(composerRecoveryKey(conflict)).draft, revision: "other-tab", text: '"other tab draft"' }));
    receiveDraftStorage(composerRecoveryKey(conflict));
    expect(saveComposerRecovery(conflict, "replacement")).toBe(false);
    expect(readComposerRecovery(conflict)).toBe("original");
    const malformed = owner("malformed");
    updateDraft(composerRecoveryKey(malformed), { text: "invalid" }); flushDraft(composerRecoveryKey(malformed));
    expect(saveComposerRecovery(malformed, "replacement")).toBe(false);
  });
});
