import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const readLoadingAsset = (name: string) =>
  readFileSync(new URL(`../../src-tauri/loading/${name}`, import.meta.url), "utf8");

describe("desktop loading assets", () => {
  it("keeps the standalone loading page wired to boot.js", () => {
    const html = readLoadingAsset("index.html");

    expect(html).toContain('<script type="module" src="./boot.js"></script>');
    expect(html).toContain('src="./spark-logo.png"');
    expect(html).toContain('id="status"');
    expect(html).toContain('id="elapsed"');
    expect(html).toContain('id="progress"');
    expect(html).toContain('id="error-note"');
    expect(html).toContain('role="progressbar"');
  });

  it("keeps backend readiness polling and timeout behavior intact", () => {
    const boot = readLoadingAsset("boot.js");

    expect(boot).toContain('const SERVER_ORIGIN = "http://127.0.0.1:9119"');
    expect(boot).toContain("const POLL_INTERVAL_MS = 250");
    expect(boot).toContain("const STARTUP_TIMEOUT_MS = 120000");
    expect(boot).toContain('fetch(SERVER_ORIGIN + "/"');
    expect(boot).toContain("window.location.replace(SERVER_ORIGIN)");
    expect(boot).toContain('document.body.dataset.state = "error"');
  });
});
