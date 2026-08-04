import type { SkillInfo } from "@/lib/api";
import {
  displayQualityValue,
  formatEvalDate,
  formatIndexTokenCost,
  normalizeSkillQuality,
  type SkillQualityInput,
} from "@/lib/skillQuality";

export function SkillQualitySignals({ skill }: { skill: SkillInfo }) {
  const quality = normalizeSkillQuality(skill as SkillQualityInput);
  const evalTone = quality.evalStatus === "pass" || quality.evalStatus === "fixture-only"
    ? "text-emerald-400/85"
    : "text-muted-foreground/75";

  return (
    <div
      className="mt-2 flex flex-wrap items-center gap-1 text-[10px] text-muted-foreground/75"
      aria-label={`${skill.name} quality signals`}
    >
      <span className="rounded border border-border/60 bg-background/30 px-1.5 py-0.5">{quality.source}</span>
      <span className="rounded border border-border/60 bg-background/30 px-1.5 py-0.5">{quality.invocationType}</span>
      <span className={`rounded px-1.5 py-0.5 ${quality.enabled ? "bg-emerald-500/8 text-emerald-400/85" : "bg-muted text-muted-foreground"}`}>
        {quality.enabled ? "Enabled" : "Disabled"}
      </span>
      <span className="px-1">{formatIndexTokenCost(quality.indexTokenCost)} index</span>
      <span className="px-1">{displayQualityValue(quality.supportingFileCount === null ? null : `${quality.supportingFileCount} files`)}</span>
      <span className={`px-1 ${evalTone}`}>Eval {quality.evalStatus} · {formatEvalDate(quality.evalDate)}</span>
      {quality.overlapWarning && (
        <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-400" title={quality.overlapWarning}>
          {quality.overlapWarning}
        </span>
      )}
    </div>
  );
}
