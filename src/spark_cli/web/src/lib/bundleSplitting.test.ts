import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const readWebSource = (path: string) =>
  readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

describe("WebUI deferred feature boundaries", () => {
  it("keeps chat eager and secondary pages and overlays lazy", () => {
    const app = readWebSource("App.tsx");

    expect(app).toContain('import ChatPage from "@/pages/ChatPage"');
    for (const feature of [
      "CanvasPage",
      "FilesPage",
      "SettingsPanel",
      "OnboardingWizard",
      "CommandPalette",
    ]) {
      expect(app).toMatch(new RegExp(`const ${feature} = lazy`));
    }
    expect(app).toContain("<LazyLoadBoundary");
  });

  it("loads editor languages by explicit dynamic import", () => {
    const editor = readWebSource("components/files/CodeEditor.tsx");

    expect(editor).toContain('import("@codemirror/lang-python")');
    expect(editor).toContain('import("@codemirror/lang-javascript")');
    expect(editor).toContain('import("@codemirror/legacy-modes/mode/yaml")');
    expect(editor).not.toMatch(/^import .*@codemirror\/lang-/m);
  });

  it("does not mount or request xterm until the terminal tab is activated", () => {
    const chat = readWebSource("pages/ChatPage.tsx");

    expect(chat).toContain("const WorkspaceTerminalPanel = lazy");
    expect(chat).toContain("terminalActivated &&");
    expect(chat).not.toContain('import { WorkspaceTerminalPanel } from');
  });

  it("keeps a visible fallback and reload recovery for chunk failures", () => {
    const boundary = readWebSource("components/LazyLoadBoundary.tsx");

    expect(boundary).toContain('role="status"');
    expect(boundary).toContain('role="alert"');
    expect(boundary).toContain("window.location.reload()");
    expect(boundary).toContain("Reload and retry");
  });
});
