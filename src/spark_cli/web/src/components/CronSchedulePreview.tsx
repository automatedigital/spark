import { useEffect, useState } from "react";
import { cronApi, type CronJobFields, type CronSchedulePreview as Preview } from "@/lib/api_cron";
import { Button } from "@/components/ui/button";

export function CronSchedulePreview({ value }: { value: Omit<CronJobFields, "prompt"> }) {
  const [result, setResult] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const key = JSON.stringify(value);
  useEffect(() => {
    const controller = new AbortController();
    setResult(null);
    setError("");
    setLoading(true);
    const timer = window.setTimeout(() => {
      cronApi.previewCronSchedule(JSON.parse(key), controller.signal).then((preview) => {
        if (!controller.signal.aborted) setResult(preview);
      }).catch((e: unknown) => {
        if (!controller.signal.aborted) {
          let message = "Could not preview schedule. Check the connection and retry.";
          try {
            const text = String(e);
            const detail = JSON.parse(text.slice(text.indexOf("{"))).detail;
            if (typeof detail === "string") message = detail;
          } catch { /* Transport errors use the actionable connection message. */ }
          setError(message);
        }
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 300);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [key, attempt]);
  return <section aria-label="Schedule preview" className="grid gap-2 rounded-md border p-3 text-sm">
    <strong>Next executions</strong>
    {loading && <p role="status">Validating schedule…</p>}
    {error && <><p role="alert">{error}</p><Button variant="outline" onClick={() => setAttempt((n) => n + 1)}>Retry preview</Button></>}
    {result && <>
      <p>Timezone: {result.timezone}</p>
      <ol>{result.occurrences.map((time) => <li key={time}><time dateTime={time}>{time}</time></li>)}</ol>
      {!result.occurrences.length && <p>No eligible future executions. Choose a future one-shot time.</p>}
      <p>Provider: {result.readiness.provider || "Unavailable"}; model: {result.readiness.model || "Runtime default"}</p>
      {result.readiness.errors.map((message) => <p role="alert" key={message}>{message}</p>)}
      <p>{result.readiness.verification}</p>
      <p>{result.missed_run_policy}</p>
      <p>{result.dst_policy}</p>
    </>}
  </section>;
}
