import { describe, expect, it } from "vitest";
import { attachmentsBlockSend, restoreAttachment, stagedAttachment } from "./attachmentStaging";
import { createComposerState, planSend } from "./chatComposerController";

describe("attachment staging", () => {
  it("blocks sending interrupted uploads after restart until removed or reattached", () => {
    const staged = stagedAttachment({ name: "draft.txt", size: 12 });
    expect(attachmentsBlockSend([staged])).toBe(true);
    const restored = restoreAttachment(JSON.parse(JSON.stringify(staged)));
    expect(restored.attachment_status).toBe("missing");
    const result = planSend(createComposerState({ contextItems: [restored] }), { messageId: "m1", text: "Read this" });
    expect(result).toMatchObject({ accepted: false, reason: "attachment-not-ready" });
    expect(attachmentsBlockSend([])).toBe(false);
  });

  it("retains server references but never reconstructs a browser File", () => {
    const staged = stagedAttachment({ name: "draft.txt", size: 12 });
    const ready = { ...staged, source_path: "files/draft.txt", attachment_status: "ready" as const };
    expect(restoreAttachment(ready)).toEqual(ready);
    expect(attachmentsBlockSend([ready])).toBe(false);
  });
});

it("retains distinct server paths and original labels for same-name draft attachments", async () => {
  const { uploadDraftFiles } = await import("./attachmentStaging");
  const { draftKey, updateDraft, flushDraft, getDraft } = await import("./draftStore");
  const storage = new Map<string, string>();
  const { vi } = await import("vitest");
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  });
  try {
    const key = draftKey({ backend: "fixture", profile: "synthetic", thread: "first" });
    let sequence = 0;
    await uploadDraftFiles(
      [{ name: "report.txt", size: 5 }, { name: "report.txt", size: 6 }] as File[],
      (change) => updateDraft(key, { contextItems: change(getDraft(key).draft.contextItems) }),
      async () => ({ saved: [{ filename: "report.txt", path: `files/report-${++sequence}.txt` }] }),
    );
    flushDraft(key);
    // A fresh module instance reads the actual persisted draft, like a reload.
    vi.resetModules();
    const reloaded = await import("./draftStore");
    const items = reloaded.getDraft(key).draft.contextItems;
    expect(items.map((item) => item.source_path)).toEqual(["files/report-1.txt", "files/report-2.txt"]);
    expect(items.map((item) => item.label)).toEqual(["report.txt", "report.txt"]);
    expect(items.map((item) => item.attachment_status)).toEqual(["ready", "ready"]);
    const other = reloaded.draftKey({ backend: "fixture", profile: "synthetic", thread: "second" });
    expect(reloaded.getDraft(other).draft.contextItems).toEqual([]);
  } finally {
    vi.unstubAllGlobals();
  }
});
