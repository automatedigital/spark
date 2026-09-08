import { makeFileContextItem, type ContextItem } from "./context";

export function stagedAttachment(file: Pick<File, "name" | "size">): ContextItem {
  return { ...makeFileContextItem("", file.size), label: file.name, attachment_status: "uploading" };
}

export function restoreAttachment(item: ContextItem): ContextItem {
  return item.attachment_status === "uploading"
    ? { ...item, attachment_status: "missing", attachment_error: "Upload interrupted. Reattach this file." }
    : item;
}

export function attachmentsBlockSend(items: readonly ContextItem[]): boolean {
  return items.some((item) => item.attachment_status && item.attachment_status !== "ready");
}

/** The setter is bound to the initiating draft, so late uploads cannot attach to another chat. */
export async function uploadDraftFiles(
  files: File[],
  setItems: (value: (items: ContextItem[]) => ContextItem[]) => void,
  upload: (file: File) => Promise<{ saved: Array<{ filename: string; path?: string }> }>,
): Promise<void> {
  const staged = files.map(stagedAttachment);
  setItems((items) => [...items, ...staged]);
  await Promise.all(staged.map(async (item, index) => {
    try {
      const result = await upload(files[index]);
      const saved = result.saved[0];
      if (!saved) throw new Error("Missing uploaded file reference");
      setItems((items) => items.map((current) => current.id === item.id
        ? { ...current, source_path: saved.path ?? `files/${saved.filename}`, attachment_status: "ready", attachment_error: undefined }
        : current));
    } catch {
      setItems((items) => items.map((current) => current.id === item.id
        ? { ...current, attachment_status: "failed", attachment_error: "Remove this item and reattach the file." }
        : current));
    }
  }));
}
