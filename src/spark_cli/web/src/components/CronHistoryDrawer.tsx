import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { readCronHistory, type CronAttempt } from "@/lib/api_cron";
import { CronOutputDrawer } from "@/components/CronOutputDrawer";

export function CronHistoryDrawer({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [entries, setEntries] = useState<CronAttempt[]>([]);
  const [cursor, setCursor] = useState<number>();
  const [next, setNext] = useState<number | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [output, setOutput] = useState<CronAttempt | null>(null);
  useEffect(() => {
    const element = dialog.current!;
    const previous = document.activeElement as HTMLElement | null;
    element.showModal();
    return () => { element.close(); previous?.focus(); };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    readCronHistory(cursor, controller.signal).then((page) => {
      if (controller.signal.aborted) return;
      setEntries((old) => cursor ? [...old, ...page.attempts] : page.attempts);
      setNext(page.next_before);
    }).catch(() => { if (!controller.signal.aborted) setError("Could not load execution history. Close and reopen to retry."); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [cursor]);
  return <dialog ref={dialog} onCancel={onClose} aria-labelledby="cron-history-title"
    className="fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-dvh w-full max-w-2xl overflow-y-auto border-l bg-background p-6 text-foreground shadow-xl backdrop:bg-black/40">
    <div className="flex justify-between"><h2 id="cron-history-title">Execution history</h2><Button onClick={onClose}>Close</Button></div>
    <p className="my-3 text-sm text-muted-foreground">Execution and delivery are separate outcomes. Unknown delivery is unconfirmed. Older receipts are pruned; legacy saved files are not attempts.</p>
    {entries.map((entry) => <article key={entry.attempt_id} className="my-3 rounded border p-3 text-sm">
      <p>Job {entry.job_id} · {entry.cause} · {new Date(entry.accepted_at).toLocaleString()}</p>
      <p>Execution: {entry.execution}</p><p>Delivery: {entry.delivery}</p>
      {entry.execution_error && <p className="text-destructive">Execution error: {entry.execution_error}</p>}
      {entry.delivery_error && <p className="text-destructive">Delivery error: {entry.delivery_error}</p>}
      <p className="text-xs text-muted-foreground">Attempt {entry.attempt_id}</p>
      {entry.output_ref && <Button variant="outline" onClick={() => setOutput(entry)}>Open saved output</Button>}
    </article>)}
    {busy && <p role="status">Loading attempts…</p>}
    {!busy && !entries.length && !error && <p>No recorded attempts.</p>}
    {error && <p role="alert">{error}</p>}
    {next && <Button disabled={busy} onClick={() => { setBusy(true); setCursor(next); }}>Load older attempts</Button>}
    {output && <CronOutputDrawer key={output.attempt_id} jobId={output.job_id} name={output.job_id}
      initialFilename={output.output_ref!.split("/")[1]} onClose={() => setOutput(null)} />}
  </dialog>;
}
