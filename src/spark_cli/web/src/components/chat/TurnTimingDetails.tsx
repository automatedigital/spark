import type { TurnTimingSummary } from "@/lib/turnTiming";
import { formatTurnDuration } from "@/lib/turnTiming";

export function TurnTimingDetails({ timing }: { timing: TurnTimingSummary }) {
  const stages = [
    ["Preparation after acceptance", timing.seconds.preparation],
    ["Execution queue", timing.seconds.queue],
    ["Acceptance to provider start", timing.seconds.provider_start],
    ["Provider start to first text token", timing.seconds.first_token],
    ["Acceptance to first text token", timing.seconds.accepted_to_first_token],
    ["Completed tools (summed; may overlap)", timing.seconds.tools],
    ["Acceptance to finish", timing.seconds.finish],
  ] as const;
  return <div className="mt-2 text-[11px] text-muted-foreground" aria-label="Latest turn timing">
    <p>Latest turn · server durations</p>
    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 mt-1">
      {stages.map(([label, value]) => <div key={label} className="contents"><dt>{label}</dt><dd>{formatTurnDuration(value)}</dd></div>)}
      <dt>Provider / model</dt><dd>{timing.provider ?? "Unknown"} / {timing.model ?? "Unknown"}</dd>
      <dt>Provider input tokens</dt><dd>{timing.usage?.prompt_tokens?.toLocaleString() ?? "Unknown"}</dd>
      <dt>Provider output tokens</dt><dd>{timing.usage?.output_tokens?.toLocaleString() ?? "Unknown"}</dd>
      <dt>Cache read / write tokens</dt><dd>{timing.usage?.cache_read_tokens?.toLocaleString() ?? "Unknown"} / {timing.usage?.cache_write_tokens?.toLocaleString() ?? "Unknown"}</dd>
    </dl>
    <p className="mt-1">Stages overlap. Unknown means unobserved or unavailable. Browser display delay is separate and is not measured here.</p>
  </div>;
}
