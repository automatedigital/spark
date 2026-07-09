import { describe, expect, it } from "vitest";
import { gatewayFooterState } from "./gatewayFooterState";
import type { StatusResponse } from "./api";

function status(overrides: Partial<StatusResponse> = {}): StatusResponse {
  return {
    gateway_running: false,
    gateway_state: "stopped",
    gateway_platforms: {},
    gateway_pid: null,
    gateway_exit_reason: null,
    active_sessions: 0,
    active_turns: [],
    version: "test",
    ...overrides,
  } as StatusResponse;
}

describe("gatewayFooterState", () => {
  it("shows reconnecting when status polling fails", () => {
    expect(gatewayFooterState(status({ gateway_running: true }), true).label).toBe("Reconnecting");
  });

  it("does not call the Web UI offline when only the messaging gateway is stopped", () => {
    const footer = gatewayFooterState(status(), false);
    expect(footer.label).toBe("Gateway stopped");
    expect(footer.title).toContain("web UI is connected");
  });

  it("shows active web chat when conversations are running without the messaging gateway", () => {
    expect(gatewayFooterState(status({ active_sessions: 2 }), false).label).toBe("Web chat active");
  });

  it("shows ready when the gateway runtime is running", () => {
    expect(gatewayFooterState(status({ gateway_running: true, gateway_pid: 1234 }), false).label).toBe("Gateway ready");
  });

  it("shows degraded when a configured platform failed while the gateway is running", () => {
    const footer = gatewayFooterState(status({
      gateway_running: true,
      gateway_platforms: {
        slack: { enabled: true, state: "fatal", error: "missing token" },
      },
    }), false);
    expect(footer.label).toBe("Gateway degraded");
  });
});
