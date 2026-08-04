import { describe, expect, it } from "vitest";
import { promptBarAvailability, promptBarKeyPolicy } from "./promptBarPolicy";

const noMenus = {
  commandMenuOpen: false,
  atMenuOpen: false,
  commandMenuHasItems: false,
};

describe("prompt bar keyboard policy", () => {
  it("submits on Enter and preserves a newline on Shift+Enter", () => {
    expect(promptBarKeyPolicy({ key: "Enter", shiftKey: false, ...noMenus })).toEqual({
      action: "submit",
      preventDefault: true,
    });
    expect(promptBarKeyPolicy({ key: "Enter", shiftKey: true, ...noMenus })).toEqual({
      action: "newline",
      preventDefault: false,
    });
  });

  it("lets an open menu own navigation and actionable Enter", () => {
    expect(promptBarKeyPolicy({
      key: "ArrowDown",
      shiftKey: false,
      commandMenuOpen: true,
      atMenuOpen: false,
      commandMenuHasItems: true,
    })).toEqual({ action: "menu", preventDefault: false });
    expect(promptBarKeyPolicy({
      key: "Enter",
      shiftKey: false,
      commandMenuOpen: true,
      atMenuOpen: false,
      commandMenuHasItems: true,
    })).toEqual({ action: "menu", preventDefault: true });
    expect(promptBarKeyPolicy({
      key: "Enter",
      shiftKey: true,
      commandMenuOpen: true,
      atMenuOpen: false,
      commandMenuHasItems: true,
    })).toEqual({ action: "newline", preventDefault: false });
  });

  it("consumes Tab while a completion menu is open", () => {
    expect(promptBarKeyPolicy({ key: "Tab", shiftKey: false, ...noMenus, commandMenuOpen: true })).toEqual({
      action: "menu",
      preventDefault: true,
    });
  });
});

describe("prompt bar action availability", () => {
  it("only enables normal submit for non-empty idle input", () => {
    expect(promptBarAvailability({
      input: "  ",
      streaming: false,
      disabled: false,
      uploading: false,
      stopRequested: false,
    })).toEqual({ hasText: false, canSubmit: false, canRedirect: false, canStop: false });
    expect(promptBarAvailability({
      input: "hello",
      streaming: false,
      disabled: false,
      uploading: false,
      stopRequested: false,
    })).toEqual({ hasText: true, canSubmit: true, canRedirect: false, canStop: false });
  });

  it("allows redirect while streaming but never normal submit", () => {
    expect(promptBarAvailability({
      input: "continue with this",
      streaming: true,
      disabled: false,
      uploading: false,
      stopRequested: false,
    })).toEqual({ hasText: true, canSubmit: false, canRedirect: true, canStop: true });
  });

  it("blocks input actions when disabled or uploading", () => {
    for (const state of [
      { disabled: true, uploading: false },
      { disabled: false, uploading: true },
    ]) {
      expect(promptBarAvailability({
        input: "hello",
        streaming: false,
        stopRequested: false,
        ...state,
      })).toMatchObject({ canSubmit: false, canRedirect: false });
    }
  });

  it("does not offer a duplicate stop after the first request", () => {
    expect(promptBarAvailability({
      input: "",
      streaming: true,
      disabled: false,
      uploading: false,
      stopRequested: true,
    }).canStop).toBe(false);
  });
});
