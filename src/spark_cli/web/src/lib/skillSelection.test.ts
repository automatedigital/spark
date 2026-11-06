import { afterEach, expect, it, vi } from "vitest";
import { acknowledgeDraft, draftKey, getDraft, updateDraft } from "./draftStore";
import { registerSkillTarget, skillTargets, stageSkill } from "./skillSelection";
import type { DiscoveredSkill } from "./skillDiscovery";

const values = new Map<string, string>();
Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
  getItem: (key: string) => values.get(key) ?? null,
  setItem: (key: string, value: string) => values.set(key, value),
} });
afterEach(() => vi.useRealTimers());

it("stages canonical selection once while retaining text/attachments and fences every draft dimension", () => {
  vi.useFakeTimers();
  const scope = { backend: "backend", profile: "profile", project: "project", thread: "thread" };
  const key = draftKey(scope);
  registerSkillTarget(key);
  const attachment = { id: "file", type: "file" as const, scope: "one_turn" as const, inclusion_mode: "full" as const, size_bytes: 7, attachment_status: "ready" as const };
  updateDraft(key, { text: "unsent words", contextItems: [attachment] });
  const skill = { skill_id: "chosen", name: "example", revision: "revision" } as DiscoveredSkill;
  stageSkill(scope, skill);
  stageSkill(scope, skill);
  const draft = getDraft(key).draft;
  expect(draft.text).toBe("unsent words");
  expect(draft.contextItems).toHaveLength(2);
  expect(draft.contextItems[0]).toEqual(attachment);
  expect(draft.contextItems[1]).toMatchObject({ type: "skill", skill_revision: "revision", skill_thread: "thread", skill_profile: "profile", skill_project: "project" });
  for (const changed of [{ backend: "other" }, { profile: "other" }, { project: "other" }, { thread: "other" }]) {
    expect(() => stageSkill({ ...scope, ...changed }, skill)).toThrow();
    expect(getDraft(draftKey({ ...scope, ...changed })).draft.contextItems).toEqual([]);
  }
  expect(skillTargets("backend", "other")).toEqual([]);
  expect(acknowledgeDraft(key, draft.revision)).toBe(true);
  expect(getDraft(key).draft.contextItems).toEqual([]);
});
