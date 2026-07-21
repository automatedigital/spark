import { describe, expect, it } from "vitest";

import { localDeviceLabel } from "./localDevice";

describe("localDeviceLabel", () => {
  it("labels Windows WebView hosts as Windows PCs", () => {
    expect(localDeviceLabel("Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Win32")).toBe(
      "Windows PC",
    );
  });

  it("labels macOS hosts as Macs", () => {
    expect(localDeviceLabel("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "MacIntel")).toBe(
      "Mac",
    );
  });

  it("labels Linux and unknown hosts without claiming they are Macs", () => {
    expect(localDeviceLabel("Mozilla/5.0 (X11; Linux x86_64)", "Linux x86_64")).toBe(
      "Linux computer",
    );
    expect(localDeviceLabel("", "")).toBe("computer");
  });
});
