import { describe, expect, it } from "vitest";
import {
  COMPOSER_A11Y_LABELS,
  COMPOSER_COMPACT_ONLY,
  COMPOSER_WIDE_ONLY,
  composerLayoutForWidth,
} from "./composerContracts";

describe("composer responsive and accessibility contract", () => {
  it("keeps model/project shortcuts wide and discovers them behind More below 1024px", () => {
    expect(composerLayoutForWidth(768)).toBe("compact");
    expect(composerLayoutForWidth(1023)).toBe("compact");
    expect(composerLayoutForWidth(1024)).toBe("wide");
    expect(composerLayoutForWidth(1440)).toBe("wide");
    expect(COMPOSER_WIDE_ONLY).toContain("min-[1024px]");
    expect(COMPOSER_COMPACT_ONLY).toContain("min-[1024px]");
  });

  it("defines labels for every always-available composer action", () => {
    expect(Object.values(COMPOSER_A11Y_LABELS)).toEqual(expect.arrayContaining([
      "Message composer",
      "Add attachments",
      "More composer options",
      "Send message",
      "Stop response",
      "Redirect with this message",
    ]));
  });
});
