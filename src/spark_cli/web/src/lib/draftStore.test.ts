import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  acknowledgeDraft,
  discardDraft,
  draftKey,
  flushDraft,
  getDraft,
  receiveDraftStorage,
  resolveDraftConflict,
  updateDraft,
} from "./draftStore";

const item = (status?: string) => ({
  id: "file-1",
  type: "file" as const,
  inclusion_mode: "path_only" as const,
  scope: "one_turn" as const,
  size_bytes: 4,
  ...(status ? { attachment_status: status } : {}),
});
let values: Map<string, string>;
let n = 0;
beforeEach(() => {
  vi.useFakeTimers();
  values = new Map();
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (k: string) => values.get(k) ?? null,
      setItem: (k: string, v: string) => values.set(k, v),
      removeItem: (k: string) => values.delete(k),
    },
  });
});
afterEach(() => vi.useRealTimers());
const scope = () =>
  draftKey({
    backend: `backend-${++n}`,
    profile: "profile-a",
    project: "project-a",
    thread: null,
  });

describe("draftStore", () => {
  it("isolates backend/profile/project and null thread", () => {
    const key = draftKey({
      backend: "a",
      profile: "p",
      project: null,
      thread: null,
    });
    updateDraft(key, { text: "new chat" });
    vi.runAllTimers();
    expect(getDraft(key).draft.text).toBe("new chat");
    expect(
      getDraft(
        draftKey({ backend: "b", profile: "p", project: null, thread: null }),
      ).draft.text,
    ).toBe("");
    expect(
      getDraft(
        draftKey({ backend: "a", profile: "p", project: null, thread: "null" }),
      ).draft.text,
    ).toBe("");
    expect(
      getDraft(
        draftKey({ backend: "a", profile: "other-profile", project: null, thread: null }),
      ).draft.text,
    ).toBe("");
    expect(
      getDraft(
        draftKey({ backend: "a", profile: "p", project: "project-a", thread: null }),
      ).draft.text,
    ).toBe("");
  });
  it("debounces updates and flushes", () => {
    const key = scope();
    updateDraft(key, { text: "draft" });
    expect(getDraft(key).status).toBe("saving");
    vi.advanceTimersByTime(350);
    expect(JSON.parse(values.get(key)!).text).toBe("draft");
    expect(getDraft(key).status).toBe("saved");
  });
  it("does not clear same text with newer revision", () => {
    const key = scope();
    updateDraft(key, { text: "same" });
    flushDraft(key);
    const submitted = getDraft(key).draft.revision;
    updateDraft(key, { text: "same" });
    expect(acknowledgeDraft(key, submitted)).toBe(false);
    expect(getDraft(key).draft.text).toBe("same");
  });
  it("keeps acknowledgement scoped", () => {
    const a = scope();
    const b = scope();
    updateDraft(a, { text: "a" });
    flushDraft(a);
    updateDraft(b, { text: "b" });
    flushDraft(b);
    expect(acknowledgeDraft(a, getDraft(a).draft.revision)).toBe(true);
    expect(getDraft(b).draft.text).toBe("b");
  });
  it("detects cross-tab race until explicit choice", () => {
    const key = scope();
    updateDraft(key, { text: "mine" });
    flushDraft(key);
    const stored = JSON.parse(values.get(key)!);
    values.set(
      key,
      JSON.stringify({ ...stored, text: "theirs", revision: "other-tab" }),
    );
    receiveDraftStorage(key);
    expect(getDraft(key).status).toBe("conflict");
    resolveDraftConflict(key, "stored");
    expect(getDraft(key).draft.text).toBe("theirs");
  });
  it("keeps memory when storage throws and can discard", () => {
    const key = scope();
    updateDraft(key, { text: "offline" });
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: {
        getItem: () => {
          throw Error("blocked");
        },
        setItem: () => {
          throw Error("blocked");
        },
      },
    });
    flushDraft(key);
    expect(getDraft(key).draft.text).toBe("offline");
    expect(getDraft(key).status).toBe("unavailable");
    discardDraft(key);
    expect(getDraft(key).draft.text).toBe("");
  });
  it("restores interrupted uploads as missing", () => {
    const key = scope();
    values.set(
      key,
      JSON.stringify({
        version: 1,
        text: "attach",
        contextItems: [item("uploading")],
        revision: "stored",
        updatedAt: Date.now(),
      }),
    );
    const restored = getDraft(key).draft.contextItems[0] as Record<
      string,
      string
    >;
    expect(restored.attachment_status).toBe("missing");
    expect(restored.attachment_error).toContain("Reattach");
  });
  it("ignores malformed storage", () => {
    const key = scope();
    values.set(key, "not-json");
    expect(() => getDraft(key)).not.toThrow();
    expect(getDraft(key).draft.text).toBe("");
  });
});
