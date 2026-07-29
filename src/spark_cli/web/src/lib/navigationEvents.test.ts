import { afterEach, describe, expect, it, vi } from "vitest";
import { emitOpenSettings, OPEN_SETTINGS_EVENT } from "./navigationEvents";

describe("settings navigation event", () => {
  afterEach(() => vi.restoreAllMocks());

  it("dispatches the shared event on window", () => {
    const listener = vi.fn();
    const fakeWindow = { dispatchEvent: listener };
    vi.stubGlobal("window", fakeWindow);
    vi.stubGlobal("CustomEvent", class CustomEvent {
      type: string;
      constructor(type: string) {
        this.type = type;
      }
    });

    emitOpenSettings();

    expect(listener).toHaveBeenCalledTimes(1);
    expect(listener.mock.calls[0][0]).toMatchObject({ type: OPEN_SETTINGS_EVENT });
  });
});
