import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  addSessionNotification,
  clearAllSessionNotifications,
  dismissSessionNotification,
  getSessionNotifications,
  getUnreadSessionCount,
  getUnreadSessionIds,
  markSessionRead,
  resetUnreadSessionStoreForTests,
  subscribeToUnreadSessions,
} from "./unreadSessionStore";

describe("unread session store", () => {
  beforeEach(() => {
    resetUnreadSessionStoreForTests();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-06-26T12:00:00Z"));
  });

  afterEach(() => {
    resetUnreadSessionStoreForTests();
    vi.useRealTimers();
  });

  it("dedupes repeated notifications for the same session", () => {
    const listener = vi.fn();
    subscribeToUnreadSessions(listener);

    addSessionNotification("s1", "Thread one", "First preview");
    addSessionNotification("s1", "Thread one", "First preview");

    expect(getUnreadSessionCount()).toBe(1);
    expect([...getUnreadSessionIds()]).toEqual(["s1"]);
    expect(getSessionNotifications()).toEqual([
      {
        sessionId: "s1",
        title: "Thread one",
        preview: "First preview",
        ts: Date.now() / 1000,
      },
    ]);
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("updates an existing notification without adding a duplicate row", () => {
    addSessionNotification("s1", "Untitled thread", null);
    vi.setSystemTime(new Date("2026-06-26T12:01:00Z"));

    addSessionNotification("s1", "Renamed thread", "Still one notification");

    expect(getUnreadSessionCount()).toBe(1);
    expect(getSessionNotifications()).toEqual([
      {
        sessionId: "s1",
        title: "Renamed thread",
        preview: "Still one notification",
        ts: Date.now() / 1000,
      },
    ]);
  });

  it("markSessionRead clears unread state and the bell entry", () => {
    const listener = vi.fn();
    subscribeToUnreadSessions(listener);
    addSessionNotification("s1", "Thread one", null);

    markSessionRead("s1");

    expect(getUnreadSessionCount()).toBe(0);
    expect(getUnreadSessionIds().has("s1")).toBe(false);
    expect(getSessionNotifications()).toEqual([]);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("dismisses one notification and keeps others unread", () => {
    addSessionNotification("s1", "Thread one", null);
    addSessionNotification("s2", "Thread two", null);

    dismissSessionNotification("s1");

    expect(getUnreadSessionCount()).toBe(1);
    expect([...getUnreadSessionIds()]).toEqual(["s2"]);
    expect(getSessionNotifications().map((n) => n.sessionId)).toEqual(["s2"]);
  });

  it("clears all notifications and unread ids", () => {
    addSessionNotification("s1", "Thread one", null);
    addSessionNotification("s2", "Thread two", null);

    clearAllSessionNotifications();

    expect(getUnreadSessionCount()).toBe(0);
    expect([...getUnreadSessionIds()]).toEqual([]);
    expect(getSessionNotifications()).toEqual([]);
  });
});
