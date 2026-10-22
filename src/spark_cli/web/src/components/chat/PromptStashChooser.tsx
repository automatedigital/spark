import { useEffect, useRef, useState } from "react";
import { deletePrompt, PROMPT_STASH_LIMIT, readPromptStash, savePrompt, type PromptStashScope, type SavedPrompt } from "@/lib/promptStashStore";

interface Props {
  scope: PromptStashScope;
  input: string;
  onRestore: (text: string) => void;
  onClose: () => void;
}

export function PromptStashChooser({ scope, input, onRestore, onClose }: Props) {
  const [items, setItems] = useState<SavedPrompt[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState<SavedPrompt | null>(null);
  const root = useRef<HTMLDialogElement>(null);
  const failure = (cause: unknown) => {
    setMessage("");
    setError(cause instanceof Error && cause.message.includes("browser storage was not changed") ? cause.message : "Browser storage is unavailable. The change was not saved. Your draft is unchanged.");
  };
  useEffect(() => {
    const dialog = root.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  useEffect(() => {
    const load = () => { try { setItems(readPromptStash(scope)); setError(""); } catch (cause) { failure(cause); } };
    load();
    window.addEventListener("storage", load);
    return () => window.removeEventListener("storage", load);
  }, [scope]);
  const restore = (item: SavedPrompt) => {
    onRestore(item.text);
    onClose();
  };
  return (
    <dialog ref={root} onCancel={onClose} aria-labelledby="prompt-stash-title" className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-xl border border-border bg-popover p-5 text-foreground shadow-xl backdrop:bg-black/50">
      <h2 id="prompt-stash-title" className="text-lg font-semibold">Saved prompts</h2>
      <p className="my-2 text-xs text-muted-foreground">Text only. Attachments and context are not saved or replaced. Stored in this browser for this backend and profile. Up to {PROMPT_STASH_LIMIT} prompts.</p>
      <button type="button" className="rounded border px-3 py-2 text-sm disabled:opacity-40" disabled={!input.trim()} onClick={() => {
        try { setItems(savePrompt(scope, input)); setError(""); setMessage("Prompt saved in this browser."); } catch (cause) {
          if (cause instanceof Error && /^(Enter prompt|Prompts can|Saved prompts are full)/.test(cause.message)) { setMessage(""); setError(cause.message); } else failure(cause);
        }
      }}>Save current prompt</button>
      {message && <p role="status" className="my-2 text-sm">{message}</p>}
      {error && <p role="alert" className="my-2 text-sm text-destructive">{error}</p>}
      {!items.length && !error && <p className="my-3 text-sm">No saved prompts yet.</p>}
      <ul className="my-3 max-h-72 space-y-2 overflow-auto">
        {items.map((item) => <li key={item.id} className="rounded border border-border p-2">
          <p className="mb-2 whitespace-pre-wrap break-words text-sm line-clamp-3">{item.text}</p>
          <button type="button" className="mr-4 text-sm underline" onClick={() => { if (input.length) setPending(item); else restore(item); }}>Restore prompt</button>
          <button type="button" className="text-sm underline" onClick={() => {
            try { setItems(deletePrompt(scope, item.id)); setPending(null); setError(""); setMessage("Saved prompt deleted."); } catch (cause) { failure(cause); }
          }}>Delete prompt</button>
        </li>)}
      </ul>
      {pending && <div className="my-3 rounded border border-border p-3">
        <p className="mb-2 text-sm">Replace your current draft text? Copy or save it first if you want to keep it.</p>
        <button type="button" className="mr-4 text-sm underline" onClick={() => restore(pending)}>Replace draft text</button>
        <button type="button" className="text-sm underline" onClick={() => setPending(null)}>Keep current draft</button>
      </div>}
      <button type="button" className="rounded border px-3 py-2 text-sm" onClick={onClose}>Close saved prompts</button>
    </dialog>
  );
}
