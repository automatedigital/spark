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
