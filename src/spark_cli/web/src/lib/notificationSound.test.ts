import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_NOTIFICATION_PREFERENCES, getNotificationPreferences, shouldPlayNotificationSound } from "./notificationPolicy";
import { createNotificationSoundPlayer, soundEventIdentity, soundKindForEvent, SOUND_COOLDOWN_MS } from "./notificationSound";

const prefs = { ...DEFAULT_NOTIFICATION_PREFERENCES, completions: true, completionSound: true, inputSound: true, quietStart: "", quietEnd: "" };
beforeEach(() => vi.stubGlobal("localStorage", { getItem: () => JSON.stringify(prefs) }));
afterEach(() => vi.unstubAllGlobals());

function fixture(state = "running") {
  let now = 0;
  const disconnect = vi.fn();
  const oscillator = { frequency: { setValueAtTime: vi.fn() }, connect: vi.fn(), start: vi.fn(), stop: vi.fn(), disconnect, onended: undefined as (() => void) | undefined };
  const context = { state, currentTime: 1, destination: {}, resume: vi.fn(async () => { context.state = "running"; }), createOscillator: vi.fn(() => oscillator), createGain: () => ({ gain: { setValueAtTime: vi.fn(), linearRampToValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() }, connect: vi.fn(), disconnect }) };
  const player = createNotificationSoundPlayer(() => context as unknown as AudioContext, () => now);
  return { player, context, oscillator, advance: () => { now += SOUND_COOLDOWN_MS; } };
}

describe("notification sounds", () => {
  it("defaults old saved preferences to silent and requires explicit boolean opt-in", () => {
    vi.stubGlobal("localStorage", { getItem: () => '{"completions":true}' });
    expect(getNotificationPreferences().completionSound).toBe(false);
    expect(getNotificationPreferences().inputSound).toBe(false);
    expect(shouldPlayNotificationSound("completion", null, getNotificationPreferences())).toBe(false);
    vi.stubGlobal("localStorage", { getItem: () => '{"completionSound":"true","inputSound":"true"}' });
    expect(shouldPlayNotificationSound("completion", null, getNotificationPreferences())).toBe(false);
    expect(shouldPlayNotificationSound("question", null, getNotificationPreferences())).toBe(false);
  });
  it("obeys class preferences, quiet hours and project mute for both sound classes", () => {
    const day = new Date(2026, 0, 1, 12);
    for (const kind of ["completion", "question", "approval"] as const) {
      expect(shouldPlayNotificationSound(kind, "active", prefs, day)).toBe(true);
      expect(shouldPlayNotificationSound(kind, "muted", { ...prefs, mutedProjects: ["muted"] }, day)).toBe(false);
      expect(shouldPlayNotificationSound(kind, null, { ...prefs, quietStart: "11:00", quietEnd: "13:00" }, day)).toBe(false);
    }
    expect(shouldPlayNotificationSound("completion", null, { ...prefs, completions: false }, day)).toBe(false);
    expect(shouldPlayNotificationSound("question", null, { ...prefs, questions: false }, day)).toBe(false);
    expect(shouldPlayNotificationSound("approval", null, { ...prefs, approvals: false }, day)).toBe(false);
    expect(shouldPlayNotificationSound("failure", null, prefs, day)).toBe(false);
  });
  it("reserves a global cooldown before simultaneous completions and inputs; dedupes after cooldown", async () => {
    const f = fixture();
    expect(await Promise.all([f.player.notify("one", "completion"), f.player.notify("two", "completion"), f.player.notify("three", "question")])).toEqual(["played", "suppressed", "suppressed"]);
    f.advance();
    expect(await f.player.notify("one", "completion")).toBe("suppressed");
    expect(await f.player.notify("four", "question")).toBe("played");
    f.oscillator.onended?.();
    expect(f.oscillator.disconnect).toHaveBeenCalled();
  });
  it("does not queue autoplay; explicit preview resumes after a gesture, even with preferences off", async () => {
    const f = fixture("suspended");
    expect(await f.player.notify("one", "completion")).toBe("blocked");
    expect(f.context.resume).not.toHaveBeenCalled();
    expect(f.oscillator.start).not.toHaveBeenCalled();
    f.advance();
    vi.stubGlobal("localStorage", { getItem: () => "{}" });
    expect(await f.player.preview("input")).toBe("played");
    expect(f.context.resume).toHaveBeenCalledOnce();
    expect(f.oscillator.stop).toHaveBeenCalledWith(1.25);
  });
  it("contains unavailable APIs and autoplay denial without rejecting or affecting later previews", async () => {
    const player = createNotificationSoundPlayer(() => { throw new Error("unsupported"); });
    expect(await player.preview("input")).toBe("blocked");
    const f = fixture("suspended");
    f.context.resume.mockRejectedValueOnce(new Error("NotAllowedError"));
    expect(await f.player.preview("input")).toBe("blocked");
    expect(await f.player.preview("input")).toBe("played");
  });
  it("never plays with preferences off", async () => {
    vi.stubGlobal("localStorage", { getItem: () => "{}" });
    const f = fixture();
    expect(await f.player.notify("one", "completion")).toBe("suppressed");
    expect(await f.player.notify("two", "question")).toBe("suppressed");
    expect(f.context.createOscillator).not.toHaveBeenCalled();
  });
  it("only classifies successful root completions and input requests, never tokens, failures or children", () => {
    expect(soundKindForEvent("chat.turn_done", { turn_outcome: { status: "completed" } })).toBe("completion");
    for (const status of ["failed", "interrupted", "running"]) expect(soundKindForEvent("chat.turn_done", { turn_outcome: { status } })).toBe(null);
    for (const topic of ["chat.token", "chat.status", "chat.subagent.completed", "chat.input_resolved"]) expect(soundKindForEvent(topic, {})).toBe(null);
    expect(soundKindForEvent("notifications.job_complete", { success: false })).toBe(null);
    expect(soundKindForEvent("chat.input_requested", {})).toBe("question");
    expect(soundKindForEvent("chat.approval_requested", {})).toBe("approval");
  });
  it("uses decision and turn identities even when transport sequences differ", () => {
    const event = { topic: "chat.input_requested", session_id: "s", data: { input: { action_id: "decision" } } };
    expect(soundEventIdentity(event, "epoch:1")).toBe(soundEventIdentity(event, "epoch:2"));
  });
});
