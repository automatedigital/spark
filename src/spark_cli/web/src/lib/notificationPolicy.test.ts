import { describe, expect, it } from "vitest";
import { DEFAULT_NOTIFICATION_PREFERENCES, isQuietHours, notificationIdentity, shouldNotify } from "./notificationPolicy";
describe("notification policy", () => {
  it("handles quiet hours crossing midnight", () => {
    const prefs = { ...DEFAULT_NOTIFICATION_PREFERENCES, quietStart: "22:00", quietEnd: "07:00" };
    expect(isQuietHours(new Date(2026, 0, 1, 23), prefs)).toBe(true);
    expect(isQuietHours(new Date(2026, 0, 1, 8), prefs)).toBe(false);
    expect(shouldNotify("approval", null, { ...prefs, approvals: false }, new Date(2026, 0, 1, 23))).toBe(true);
  });
  it("deduplicates by stable event identity", () => {
    expect(notificationIdentity({ topic: "notifications.job_complete", ts: 3, data: { job_id: "x" } })).toBe("notifications.job_complete:x:3");
    expect(notificationIdentity({ id: "event-1", topic: "x" })).toBe("event-1");
  });
});
