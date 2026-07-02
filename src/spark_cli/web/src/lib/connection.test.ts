import { describe, it, expect, vi } from "vitest";
import {
  normalizeBaseUrl,
  isValidBaseUrl,
  isValidToken,
  probeUrl,
  resolveApiBase,
  parseConnectionMode,
  displayHost,
  validateRemoteConnection,
} from "./connection";

describe("normalizeBaseUrl", () => {
  it("strips trailing slashes", () => {
    expect(normalizeBaseUrl("https://x.com/")).toBe("https://x.com");
    expect(normalizeBaseUrl("https://x.com///")).toBe("https://x.com");
  });
  it("keeps a sub-path but drops its trailing slash", () => {
    expect(normalizeBaseUrl("https://x.com/spark/")).toBe("https://x.com/spark");
  });
  it("trims whitespace", () => {
    expect(normalizeBaseUrl("  https://x.com  ")).toBe("https://x.com");
  });
  it("rejects empty / non-http / garbage", () => {
    expect(normalizeBaseUrl("")).toBeNull();
    expect(normalizeBaseUrl("   ")).toBeNull();
    expect(normalizeBaseUrl("ftp://x.com")).toBeNull();
    expect(normalizeBaseUrl("not a url")).toBeNull();
  });
});

describe("isValidBaseUrl / isValidToken", () => {
  it("validates urls", () => {
    expect(isValidBaseUrl("http://localhost:9119")).toBe(true);
    expect(isValidBaseUrl("nope")).toBe(false);
  });
  it("validates tokens", () => {
    expect(isValidToken("token123")).toBe(true);
    expect(isValidToken("placeholder")).toBe(false);
    expect(isValidToken("   ")).toBe(false);
    expect(isValidToken("")).toBe(false);
  });
});

describe("probeUrl", () => {
  it("appends /api/config to a normalized base", () => {
    expect(probeUrl("https://x.com")).toBe("https://x.com/api/config");
  });
  it("is robust to a stray trailing slash", () => {
    expect(probeUrl("https://x.com/")).toBe("https://x.com/api/config");
  });
});

describe("resolveApiBase", () => {
  it("returns empty string for local mode", () => {
    expect(resolveApiBase("local", "https://x.com")).toBe("");
  });
  it("returns normalized base for remote mode", () => {
    expect(resolveApiBase("remote", "https://x.com/")).toBe("https://x.com");
  });
  it("falls back to same-origin when remote url missing/invalid", () => {
    expect(resolveApiBase("remote", null)).toBe("");
    expect(resolveApiBase("remote", "garbage")).toBe("");
  });
});

describe("parseConnectionMode", () => {
  it("defaults to local", () => {
    expect(parseConnectionMode(null)).toBe("local");
    expect(parseConnectionMode("anything")).toBe("local");
    expect(parseConnectionMode("remote")).toBe("remote");
  });
});

describe("displayHost", () => {
  it("extracts host", () => {
    expect(displayHost("https://vps.example.com:8080/x")).toBe("vps.example.com:8080");
    expect(displayHost(null)).toBe("");
  });
});

describe("validateRemoteConnection", () => {
  const fakeRes = (ok: boolean, status: number) =>
    ({ ok, status }) as Response;

  it("rejects invalid url before fetching", async () => {
    const fetchSpy = vi.fn();
    const r = await validateRemoteConnection("bad", "token123", fetchSpy as unknown as typeof fetch);
    expect(r.ok).toBe(false);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rejects missing token before fetching", async () => {
    const fetchSpy = vi.fn();
    const r = await validateRemoteConnection("https://x.com", "  ", fetchSpy as unknown as typeof fetch);
    expect(r.ok).toBe(false);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("probes the right url with a bearer token and succeeds on 200", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(fakeRes(true, 200));
    const r = await validateRemoteConnection("https://x.com/", "token123", fetchSpy as unknown as typeof fetch);
    expect(r.ok).toBe(true);
    expect(fetchSpy).toHaveBeenCalledWith("https://x.com/api/config", {
      headers: { Authorization: "Bearer token123" },
    });
  });

  it("reports invalid token on 401", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(fakeRes(false, 401));
    const r = await validateRemoteConnection("https://x.com", "token123", fetchSpy as unknown as typeof fetch);
    expect(r).toMatchObject({ ok: false, status: 401 });
  });

  it("reports network errors", async () => {
    const fetchSpy = vi.fn().mockRejectedValue(new Error("boom"));
    const r = await validateRemoteConnection("https://x.com", "token123", fetchSpy as unknown as typeof fetch);
    expect(r.ok).toBe(false);
    expect(r.error).toContain("boom");
  });
});
