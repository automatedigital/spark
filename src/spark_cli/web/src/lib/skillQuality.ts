import type { SkillInfo, SkillSupportingFile } from "@/lib/api";

/** Optional quality metadata returned by newer skill inventory endpoints. */
export interface SkillQualityFields {
  provenance?: string | null;
  source?: string | null;
  invocation_type?: string | null;
  enabled?: boolean | null;
  index_token_cost?: number | null;
  supporting_file_count?: number | null;
  supporting_files?: SkillSupportingFile[] | null;
  eval_status?: string | null;
  eval_date?: string | null;
  overlap_warning?: string | boolean | null;
}

export type SkillQualityInput = SkillInfo & SkillQualityFields;

export interface SkillQualitySnapshot {
  source: string;
  invocationType: string;
  enabled: boolean;
  indexTokenCost: number | null;
  supportingFileCount: number | null;
  evalStatus: string;
  evalDate: string | null;
  overlapWarning: string | null;
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function finiteNonNegative(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

function sourceFrom(skill: SkillQualityInput): string {
  return (
    nonEmptyString(skill.source) ??
    nonEmptyString(skill.provenance_detail?.source) ??
    nonEmptyString(skill.provenance) ??
    "local"
  );
}

export function normalizeSkillQuality(skill: SkillQualityInput): SkillQualitySnapshot {
  const overlap = skill.overlap_warning;
  const overlapWarning = typeof overlap === "boolean" ? (overlap ? "Potential overlap" : null) : nonEmptyString(overlap);
  const supportingFileCount = finiteNonNegative(skill.supporting_file_count) ??
    (Array.isArray(skill.supporting_files) ? skill.supporting_files.length : null);

  return {
    source: sourceFrom(skill),
    invocationType: nonEmptyString(skill.invocation_type) ?? "unknown",
    enabled: typeof skill.enabled === "boolean" ? skill.enabled : false,
    indexTokenCost: finiteNonNegative(skill.index_token_cost),
    supportingFileCount,
    evalStatus: nonEmptyString(skill.eval_status) ?? "not evaluated",
    evalDate: nonEmptyString(skill.eval_date),
    overlapWarning,
  };
}

export function formatIndexTokenCost(value: number | null): string {
  if (value === null) return "—";
  if (value < 1000) return `~${Math.round(value)} tok`;
  return `~${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k tok`;
}

export function formatEvalDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

export function displayQualityValue(value: string | number | null): string {
  return value === null || value === "" ? "—" : String(value);
}
