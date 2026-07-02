import { describe, expect, it } from "vitest";
import {
  hasUsableSecret,
  normalizeHttpBaseUrl,
  normalizePort,
  validateHttpBaseUrl,
  validateModelName,
  validateSecret,
} from "./onboardingValidation";

describe("normalizeHttpBaseUrl", () => {
  it("normalizes valid http(s) URLs", () => {
    expect(normalizeHttpBaseUrl(" http://localhost:11434/ ")).toBe("http://localhost:11434");
    expect(normalizeHttpBaseUrl("https://example.com/v1///")).toBe("https://example.com/v1");
  });

  it("rejects missing schemes, non-http schemes, bad ports, and query strings", () => {
    expect(normalizeHttpBaseUrl("localhost:11434")).toBeNull();
    expect(normalizeHttpBaseUrl("ftp://host")).toBeNull();
    expect(normalizeHttpBaseUrl("http://host:0")).toBeNull();
    expect(normalizeHttpBaseUrl("http://host:65536")).toBeNull();
    expect(normalizeHttpBaseUrl("http://host/path?q=1")).toBeNull();
  });

  it("returns a useful error message", () => {
    expect(validateHttpBaseUrl("localhost:11434", "Ollama base URL")).toMatchObject({
      ok: false,
      error: expect.stringContaining("Ollama base URL"),
    });
  });
});

describe("normalizePort", () => {
  it("accepts valid port numbers", () => {
    expect(normalizePort("22")).toBe("22");
    expect(normalizePort(" 8644 ")).toBe("8644");
  });

  it("rejects invalid port values", () => {
    for (const raw of ["0", "65536", "abc", "22x", ""]) {
      expect(normalizePort(raw)).toBeNull();
    }
  });
});

describe("secret and model validation", () => {
  it("rejects empty, short, and placeholder secrets", () => {
    expect(hasUsableSecret("placeholder")).toBe(false);
    expect(hasUsableSecret("abc")).toBe(false);
    expect(validateSecret("your-api-key", "API key").ok).toBe(false);
  });

  it("accepts real-looking secrets after trimming", () => {
    expect(validateSecret("  sk-test-value\n", "API key")).toMatchObject({
      ok: true,
      value: "sk-test-value",
    });
  });

  it("validates conservative model identifiers", () => {
    expect(validateModelName("anthropic/claude-sonnet-4-6")).toMatchObject({ ok: true });
    expect(validateModelName("bad model").ok).toBe(false);
    expect(validateModelName("").ok).toBe(false);
  });
});
