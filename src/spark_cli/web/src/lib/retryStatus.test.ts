import { describe, expect, it } from "vitest";
import { RETRY_STATUS_PREFIX, parseRetryStatus, retryDisplayLabel, retryStatusLabel, shouldRefreshRetryStatus } from "./retryStatus";
import { resolveChatStatus } from "./chatStatus";

const data = {
  version: 1, reason_class: "rate_limit", attempt: 2, max_attempts: 3,
  next_delay_seconds: 10, next_attempt_at: 1010, observed_at: 1000,
  elapsed_seconds: 0, budget_seconds: 240, budget_deadline_at: 1240,
};
const wire = RETRY_STATUS_PREFIX + JSON.stringify(data);

describe("confirmed retry status", () => {
  it("reconciles live retry entry and exit without polling ordinary token events", () => {
    expect(shouldRefreshRetryStatus("chat.status", { kind: "retry", message: wire }, "api")).toBe(true);
    expect(shouldRefreshRetryStatus("chat.status", { kind: "api", message: "Calling model" }, "retry")).toBe(true);
    expect(shouldRefreshRetryStatus("chat.token", { t: "first" }, "retry")).toBe(true);
    expect(shouldRefreshRetryStatus("chat.token", { t: "next" }, "streaming")).toBe(false);
    expect(shouldRefreshRetryStatus("chat.status", { kind: "retry", message: "malformed" }, "api")).toBe(false);
    expect(shouldRefreshRetryStatus("chat.status", { kind: "api", message: "Calling model" }, "api")).toBe(false);
  });
  it("shows reason, attempt and countdown from one sparse backend deadline", () => {
    const status = parseRetryStatus(wire)!;
    expect(retryStatusLabel(status, 1_000_000)).toBe("Rate limit · retry 2/3 · in 10s");
    expect(retryStatusLabel(status, 1_004_000)).toBe("Rate limit · retry 2/3 · in 6s");
    expect(retryStatusLabel(status, 1_011_000)).toContain("awaiting provider");
    expect(retryStatusLabel(status, 1_241_000)).toContain("waiting for backend status");
  });
  it("reconciles a backend snapshot and lets Stop/offline/terminal state take precedence", () => {
    const input = { turnActive: true, backendState: "running", backendPhase: "retry", backendLabel: wire, now: 1_000_000 };
    expect(resolveChatStatus(input)).toMatchObject({ kind: "retrying", confirmed: true, label: "Rate limit · retry 2/3 · in 10s" });
    expect(resolveChatStatus({ ...input, backendState: "stopping" }).kind).toBe("stopping");
    expect(resolveChatStatus({ ...input, connection: "offline" }).kind).toBe("offline");
    expect(resolveChatStatus({ ...input, turnActive: false }).kind).toBe("idle");
    expect(resolveChatStatus({ turnActive: false, backendState: "not_found" }).label).toBeNull();
  });
  it("does not display malformed wire data or trust unbounded deadlines", () => {
    for (const invalid of ["{", JSON.stringify({ ...data, attempt: 99 }), JSON.stringify({ ...data, next_attempt_at: 9999 }), JSON.stringify({ ...data, reason_class: "secret provider response" })]) {
      expect(parseRetryStatus(RETRY_STATUS_PREFIX + invalid)).toBeNull();
      expect(retryDisplayLabel(RETRY_STATUS_PREFIX + invalid, 0)).toBe("Retry status unavailable");
    }
  });
});
