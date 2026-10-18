import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatPanelOwnership, isChatPanelScopeCurrent } from "./chatPanelOwnership";
import { sidebarPreferenceKey, sidebarPreferenceScopeGeneration, setSidebarPreferenceScope } from "./sidebarPrefs";
import { apiConnectionGeneration, clearDashboardToken, setDashboardToken, setLocalConnection, setRemoteConnection } from "./apiHelpers";

afterEach(() => { vi.unstubAllGlobals(); setSidebarPreferenceScope("unresolved"); });

describe("navigation panel ownership", () => {
  it("retires held scope actions after same-base credential replacement/ABA, with idempotent setters", () => {
    const storage = new Map<string, string>();
    vi.stubGlobal("localStorage", { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) });
    setRemoteConnection("http://127.0.0.1:23456", "fixture-A");
    const generation = apiConnectionGeneration();
    const navigation = new ChatPanelOwnership();
    const owner = navigation.navigate(sidebarPreferenceKey("chat"), "A", sidebarPreferenceScopeGeneration(), generation);
    setDashboardToken(" fixture-A ");
    setRemoteConnection("http://127.0.0.1:23456/", "fixture-A");
    expect(apiConnectionGeneration()).toBe(generation);
    expect(isChatPanelScopeCurrent(owner)).toBe(true);
    setDashboardToken("fixture-B");
    setDashboardToken("fixture-A");
    expect(apiConnectionGeneration()).toBe(generation + 2);
    expect(isChatPanelScopeCurrent(owner)).toBe(false);
    clearDashboardToken();
    expect(apiConnectionGeneration()).toBe(generation + 3);
    clearDashboardToken();
    setDashboardToken("  ");
    expect(apiConnectionGeneration()).toBe(generation + 3);
    // Even a mode-only transition with the same effective base retires scope.
    setRemoteConnection("", "");
    const modeGeneration = apiConnectionGeneration();
    setLocalConnection();
    expect(apiConnectionGeneration()).toBe(modeGeneration + 1);
  });
  it("preserves same-scope origin effects but never revives after profile or backend A-B-A", () => {
    const storage = new Map<string, string>();
    vi.stubGlobal("localStorage", { getItem: (key: string) => storage.get(key) ?? null, setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) });
    setSidebarPreferenceScope("profile-A");
    const navigation = new ChatPanelOwnership();
    const owner = navigation.navigate(sidebarPreferenceKey("chat"), "A", sidebarPreferenceScopeGeneration(), apiConnectionGeneration());
    const profileGeneration = sidebarPreferenceScopeGeneration();
    setSidebarPreferenceScope("profile-A");
    expect(sidebarPreferenceScopeGeneration()).toBe(profileGeneration);
    navigation.navigate(sidebarPreferenceKey("chat"), "B", sidebarPreferenceScopeGeneration(), apiConnectionGeneration());
    expect(owner.isCurrent()).toBe(false);
    expect(isChatPanelScopeCurrent(owner)).toBe(true);
    setSidebarPreferenceScope("profile-B");
    setSidebarPreferenceScope("profile-A");
    expect(sidebarPreferenceScopeGeneration()).toBe(profileGeneration + 2);
    expect(isChatPanelScopeCurrent(owner)).toBe(false);
    const fresh = navigation.navigate(sidebarPreferenceKey("chat"), "A", sidebarPreferenceScopeGeneration(), apiConnectionGeneration());
    const backendGeneration = apiConnectionGeneration();
    setLocalConnection();
    expect(apiConnectionGeneration()).toBe(backendGeneration);
    setRemoteConnection("http://127.0.0.1:23456", "fixture");
    setRemoteConnection("http://127.0.0.1:23456/", "fixture");
    expect(apiConnectionGeneration()).toBe(backendGeneration + 1);
    setLocalConnection();
    expect(apiConnectionGeneration()).toBe(backendGeneration + 2);
    expect(isChatPanelScopeCurrent(fresh)).toBe(false);
  });

  it("adopts a null-created ID only for the original request and owner", () => {
    const navigation = new ChatPanelOwnership();
    const owner = navigation.navigate("backend/profile", null);
    const request = owner.beginRequest()!;
    expect(request.previousID).toBeNull();
    expect(navigation.adopt({ ...request, nextID: "created", reason: "send-continuation" }, request.scope)).toBe(true);
    expect(navigation.navigate(request.scope, "created")).toBe(owner);
    expect(navigation.adopt({ ...request, nextID: "duplicate", reason: "send-continuation" }, request.scope)).toBe(false);
  });
  it("retires A on A-B-A and never reuses its request or owner", () => {
    const navigation = new ChatPanelOwnership();
    const firstA = navigation.navigate("backend/profile", "A");
    const pending = firstA.beginRequest()!;
    const b = navigation.navigate("backend/profile", "B");
    const secondA = navigation.navigate("backend/profile", "A");
    expect(new Set([firstA.ownerToken, b.ownerToken, secondA.ownerToken]).size).toBe(3);
    expect(firstA.isCurrent()).toBe(false);
    expect(firstA.beginRequest()).toBeNull();
    expect(navigation.adopt({ ...pending, nextID: "late-A", reason: "send-continuation" }, pending.scope)).toBe(false);
    expect(secondA.isCurrent()).toBe(true);
  });

  it("keeps a continuing owner through renders and acknowledged send-ID catchup", () => {
    const navigation = new ChatPanelOwnership();
    const owner = navigation.navigate("backend/profile", "A");
    const request = owner.beginRequest()!;
    for (let i = 0; i < 100; i++) expect(navigation.navigate(request.scope, "A")).toBe(owner);
    expect(navigation.adopt({ ...request, nextID: "compressed-A", reason: "send-continuation" }, request.scope)).toBe(true);
    expect(navigation.navigate(request.scope, "compressed-A")).toBe(owner);
    expect(owner.isCurrent()).toBe(true);
  });

  it("gives fork a fresh owner and rejects superseded or cross-scope adoption", () => {
    const navigation = new ChatPanelOwnership();
    const owner = navigation.navigate("backend/profile", "A");
    const stale = owner.beginRequest()!;
    const current = owner.beginRequest()!;
    expect(navigation.adopt({ ...stale, nextID: "stale", reason: "fork" }, stale.scope)).toBe(false);
    expect(navigation.adopt({ ...current, nextID: "fork", reason: "fork" }, "backend/other-profile")).toBe(false);
    expect(navigation.adopt({ ...current, previousID: "other", nextID: "fork", reason: "fork" }, current.scope)).toBe(false);
    expect(navigation.adopt({ ...current, nextID: "fork", reason: "fork" }, current.scope)).toBe(true);
    expect(navigation.navigate(current.scope, "fork").ownerToken).not.toBe(owner.ownerToken);
    const fork = navigation.navigate(current.scope, "fork");
    navigation.retire();
    expect(fork.isCurrent()).toBe(false);
    expect(fork.beginRequest()).toBeNull();
  });

  it("bounds primitive bookmarks and separates backend/profile/session", () => {
    const navigation = new ChatPanelOwnership();
    const source = { top: 100, anchorId: "turn:user:db:1", offset: -12, extra: { transcript: [] } };
    navigation.saveBookmark("backend/profile", "A", source);
    expect(navigation.readBookmark("backend/profile", "A")).toEqual({ top: 100, anchorId: source.anchorId, offset: -12 });
    expect(navigation.readBookmark("other-backend/profile", "A")).toBeNull();
    expect(navigation.readBookmark("backend/other-profile", "A")).toBeNull();
    for (let i = 0; i < 101; i++) navigation.saveBookmark("backend/profile", String(i), source);
    expect(navigation.bookmarks.size).toBe(100);
    expect(navigation.readBookmark("backend/profile", "A")).toBeNull();
    navigation.saveBookmark("backend/profile", "100", null);
    expect(navigation.bookmarks.size).toBe(99);
  });
});
