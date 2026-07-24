import { describe, expect, it } from "vitest";

import { isDirectPreviewUrl } from "./previewUrl";

describe("isDirectPreviewUrl", () => {
  it.each([
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://joes-mbp.local:5468",
    "http://[::1]:5173",
  ])("embeds a machine-local preview directly: %s", (url) => {
    expect(isDirectPreviewUrl(url, "127.0.0.1")).toBe(true);
  });

  it("embeds a preview served from the dashboard hostname", () => {
    expect(isDirectPreviewUrl("http://sparkbox.internal:5173", "sparkbox.internal")).toBe(true);
  });

  it("uses the streamed browser for a genuinely external origin", () => {
    expect(isDirectPreviewUrl("https://example.com", "127.0.0.1")).toBe(false);
  });
});
