import { describe, expect, it } from "vitest";
import { SettingsDraftOwner } from "./settingsDrafts";

describe("Settings draft ownership", () => {
  it("retains only the selected tab's draft, including empty and false edits", () => {
    const owner = new SettingsDraftOwner("profile-a:epoch-1");
    owner.write("model:config", { model: "custom/model" }, owner.scope);
    owner.write("config:yaml", "", owner.scope);
    owner.write("messaging:enabled", false, owner.scope);
    expect(owner.read("model:config", null)).toEqual({ model: "custom/model" });
    expect(owner.read("config:yaml", "server" )).toBe("");
    expect(owner.read("messaging:enabled", true)).toBe(false);
    expect(owner.read("chat:config", null)).toBeNull();
  });
  it("never transfers drafts to a reopened dialog or another profile/credential epoch", () => {
    const old = new SettingsDraftOwner("a:1");
    old.write("model:key", "synthetic-secret", "a:1");
    for (const scope of ["a:1", "b:2", "a:3"]) {
      expect(new SettingsDraftOwner(scope).read("model:key", "")).toBe("");
    }
    expect(old.write("model:key", "late", "a:3")).toBe(false);
    expect(old.read("model:key", "")).toBe("synthetic-secret");
  });
});
