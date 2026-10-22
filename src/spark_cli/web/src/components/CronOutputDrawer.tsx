import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { savedOutputsApi, type SavedOutput } from "@/lib/api_cron_outputs";

/** Mounted per job so pending requests cannot populate a different job's drawer. */
export function CronOutputDrawer({ jobId, name, onClose }: { jobId: string; name: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [files, setFiles] = useState<string[]>([]);
  const [before, setBefore] = useState<string | null>(null);
  const [selected, setSelected] = useState("");
  const [output, setOutput] = useState<SavedOutput | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [page, setPage] = useState<string | undefined>();
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    const element = dialog.current!;
    const previous = document.activeElement as HTMLElement | null;
    element.showModal();
    return () => { element.close(); previous?.focus(); };
  }, []);

  useEffect(() => {
    let active = true;
    savedOutputsApi.list(jobId, page).then((result) => {
      if (!active) return;
      setFiles((old) => page ? [...old, ...result.files] : result.files);
      setBefore(result.next_before);
      if (!page && result.files.length) setSelected(result.files[0]);
    }).catch(() => { if (active) setError("Could not load saved output history. Close and reopen to retry."); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [jobId, page]);

  useEffect(() => {
    if (!selected) return;
    let active = true;
    savedOutputsApi.read(jobId, selected).then((result) => {
      if (active) setOutput(result);
    }).catch(() => { if (active) setError("Saved output is unavailable or was pruned. Choose another document or reopen history."); });
    return () => { active = false; };
  }, [jobId, selected]);

  const choose = (filename: string) => {
    setOutput(null); setError(""); setCopied(false); setSelected(filename);
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(output!.content); setCopied(true); }
    catch { setError("Could not copy. Select and copy the document text below."); }
  };

  return <dialog ref={dialog} onCancel={onClose} aria-labelledby="saved-output-title"
    className="fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-dvh w-full max-w-2xl overflow-y-auto border-l bg-background p-6 text-foreground shadow-xl backdrop:bg-black/40">
    <div className="flex items-start justify-between gap-4">
      <div><h2 id="saved-output-title" className="text-lg font-semibold">Saved output history</h2><p className="break-words">{name}</p></div>
      <Button variant="ghost" onClick={onClose}>Close</Button>
    </div>
    <p className="my-3 text-sm text-muted-foreground">Saved Markdown documents, newest first. These files do not confirm execution attempts or delivery.</p>
    {busy && <p role="status">Loading saved outputs…</p>}
    {!busy && !files.length && !error && <p>No saved outputs. Files may have been pruned.</p>}
    <div className="flex max-h-56 flex-col items-start gap-2 overflow-y-auto border-b py-2">
      {files.map((filename) => <Button key={filename} variant={selected === filename ? "secondary" : "ghost"}
        aria-pressed={selected === filename} onClick={() => choose(filename)}>{filename}</Button>)}
      {before && <Button disabled={busy} onClick={() => { setBusy(true); setError(""); setPage(before); }}>Load older outputs</Button>}
    </div>
    {error && <p role="alert" className="my-3 text-destructive">{error}</p>}
    {selected && !output && !error && <p role="status">Loading document…</p>}
    {output && <section className="mt-4" aria-label="Saved document">
      <Button onClick={copy}>{copied ? "Copied" : output.truncated ? "Copy displayed text" : "Copy Markdown"}</Button>
      {output.truncated && <p role="status">Showing the first {output.max_bytes.toLocaleString()} bytes. Copy includes only displayed text.</p>}
      <pre className="mt-3 max-h-[50vh] overflow-auto whitespace-pre-wrap break-words rounded border p-3 text-sm">{output.content}</pre>
    </section>}
  </dialog>;
}
