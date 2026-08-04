import { describe, expect, it } from "vitest";
import { displayQualityValue, formatEvalDate, formatIndexTokenCost, normalizeSkillQuality, type SkillQualityInput } from "@/lib/skillQuality";

const skill = (fields: Partial<SkillQualityInput> = {}): SkillQualityInput => ({
  name: "example",
  description: "Example skill",
  category: "engineering",
  enabled: true,
  use_count: 0,
  view_count: 0,
  patch_count: 0,
  skill_state: "active",
  ...fields,
});

describe("normalizeSkillQuality", () => {
  it("reads the exact quality fields without changing their meaning", () => {
    expect(normalizeSkillQuality(skill({
      source: "mattpocock/skills",
      invocation_type: "user_invoked",
      enabled: false,
      index_token_cost: 1240,
      supporting_file_count: 3,
      eval_status: "pass",
      eval_date: "2026-08-04",
      overlap_warning: "overlaps with planning",
    }))).toEqual({
      source: "mattpocock/skills",
      invocationType: "user_invoked",
      enabled: false,
      indexTokenCost: 1240,
      supportingFileCount: 3,
      evalStatus: "pass",
      evalDate: "2026-08-04",
      overlapWarning: "overlaps with planning",
    });
  });

  it("falls back safely for older servers", () => {
    expect(normalizeSkillQuality(skill({ provenance: "bundled", provenance_detail: { label: "Spark built-in", source: "Spark" } }))).toEqual({
      source: "Spark",
      invocationType: "unknown",
      enabled: true,
      indexTokenCost: null,
      supportingFileCount: null,
      evalStatus: "not evaluated",
      evalDate: null,
      overlapWarning: null,
    });
  });

  it("uses supporting files as a compatibility fallback and handles boolean warnings", () => {
    expect(normalizeSkillQuality(skill({ supporting_files: [{ path: "helper.ts", size: 12, file_type: "file" }], overlap_warning: true }))).toMatchObject({
      supportingFileCount: 1,
      overlapWarning: "Potential overlap",
    });
    expect(normalizeSkillQuality(skill({ overlap_warning: false })).overlapWarning).toBeNull();
  });
});

describe("quality display formatting", () => {
  it("keeps compact token labels and safe date fallbacks", () => {
    expect(formatIndexTokenCost(840)).toBe("~840 tok");
    expect(formatIndexTokenCost(1240)).toBe("~1.2k tok");
    expect(formatIndexTokenCost(null)).toBe("—");
    expect(formatEvalDate("not-a-date")).toBe("not-a-date");
    expect(displayQualityValue(null)).toBe("—");
  });
});
