import { afterEach, expect, it, vi } from "vitest";
import { postRootSubmission } from "./api_submissions";
import { setSidebarPreferenceScope } from "./sidebarPrefs";

afterEach(() => vi.unstubAllGlobals());

it("retains the default new-chat receipt across a lost response and retires it after acceptance", async () => {
  const bodies: Array<{ submission_id: string }> = [];
  const fetch = vi.fn(async (_url: unknown, init: RequestInit) => {
    bodies.push(JSON.parse(String(init.body)));
    if (bodies.length === 1) throw new Error("response dropped after commit");
    return new Response(JSON.stringify({ ok: true, session_id: "accepted-thread" }));
  });
  vi.stubGlobal("fetch", fetch);
  setSidebarPreferenceScope("submission-test");
  const payload = { message: "same draft", context_items: [] };
  await expect(postRootSubmission("/api/conversations", payload)).rejects.toThrow("dropped");
  await postRootSubmission("/api/conversations", payload);
  expect(bodies[1].submission_id).toBe(bodies[0].submission_id);
  await postRootSubmission("/api/conversations", payload);
  expect(bodies[2].submission_id).not.toBe(bodies[0].submission_id);
});

it("separates profile and payload identities while preserving an unresolved draft", async () => {
  const ids: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init: RequestInit) => {
    ids.push(JSON.parse(String(init.body)).submission_id);
    throw new Error("ambiguous");
  }));
  const send = async (message = "draft") => {
    await expect(postRootSubmission("/api/conversations", { message })).rejects.toThrow("ambiguous");
  };
  setSidebarPreferenceScope("profile-a");
  await send();
  await send("changed");
  setSidebarPreferenceScope("profile-b");
  await send();
  setSidebarPreferenceScope("profile-a");
  await send();
  expect(new Set(ids.slice(0, 3)).size).toBe(3);
  expect(ids[3]).toBe(ids[0]);
});
