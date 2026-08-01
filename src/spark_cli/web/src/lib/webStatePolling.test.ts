import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

describe("healthy push transport", () => {
  it("has no eight-second status poll or two-second chat recovery loop", () => {
    const root = path.resolve(import.meta.dirname, "..");
    const app = fs.readFileSync(path.join(root, "App.tsx"), "utf8");
    const chat = fs.readFileSync(path.join(root, "components/ChatPanel.tsx"), "utf8");
    expect(app).not.toContain("8_000");
    expect(chat).not.toContain("setInterval(tick, 2_000)");
  });

  it("keeps only a stale watchdog interval in the central supervisor", () => {
    const source = fs.readFileSync(path.resolve(import.meta.dirname, "../hooks/useEventBus.ts"), "utf8");
    expect(source).toContain("STALE_AFTER_MS");
    expect(source.match(/window\.setInterval/g)).toHaveLength(1);
    expect(source).toContain("Date.now() - this.lastEventAt < STALE_AFTER_MS");
  });

  it("hydrates a new document before using any retained resume cursor", () => {
    const source = fs.readFileSync(path.resolve(import.meta.dirname, "../hooks/useEventBus.ts"), "utf8");
    const bootstrap = source.slice(source.indexOf("private bootstrap"), source.indexOf("private fetchSnapshot"));
    expect(source).toContain("private cursor: Cursor | null = null");
    expect(source).not.toContain("readCursor()");
    expect(bootstrap).toContain("await this.fetchSnapshot()");
    expect(bootstrap).not.toContain("fetchDeltas()");
  });
});
