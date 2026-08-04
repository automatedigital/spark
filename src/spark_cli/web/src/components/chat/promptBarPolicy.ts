export type PromptBarKeyAction = "submit" | "newline" | "menu" | "noop";

export interface PromptBarKeyPolicyInput {
  key: string;
  shiftKey: boolean;
  commandMenuOpen: boolean;
  atMenuOpen: boolean;
  commandMenuHasItems: boolean;
}

export interface PromptBarKeyPolicy {
  action: PromptBarKeyAction;
  preventDefault: boolean;
}

/**
 * Keep keyboard handling independent from the textarea and menu components.
 * The menu cases mirror PromptBar's existing event ownership: navigation and
 * Escape are left to the menu, while Tab and an actionable Enter are consumed.
 */
export function promptBarKeyPolicy({
  key,
  shiftKey,
  commandMenuOpen,
  atMenuOpen,
  commandMenuHasItems,
}: PromptBarKeyPolicyInput): PromptBarKeyPolicy {
  const menuOpen = commandMenuOpen || atMenuOpen;
  if (menuOpen) {
    if (["ArrowUp", "ArrowDown", "Escape"].includes(key)) {
      return { action: "menu", preventDefault: false };
    }
    if (key === "Tab") {
      return { action: "menu", preventDefault: true };
    }
    if (key === "Enter" && !shiftKey && (commandMenuHasItems || atMenuOpen)) {
      return { action: "menu", preventDefault: true };
    }
  }

  if (key === "Enter" && !shiftKey) {
    return { action: "submit", preventDefault: true };
  }
  if (key === "Enter" && shiftKey) {
    return { action: "newline", preventDefault: false };
  }
  return { action: "noop", preventDefault: false };
}

export interface PromptBarAvailabilityInput {
  input: string;
  streaming: boolean;
  disabled: boolean;
  uploading: boolean;
  stopRequested: boolean;
}

export interface PromptBarAvailability {
  hasText: boolean;
  canSubmit: boolean;
  canRedirect: boolean;
  canStop: boolean;
}

export function promptBarAvailability({
  input,
  streaming,
  disabled,
  uploading,
  stopRequested,
}: PromptBarAvailabilityInput): PromptBarAvailability {
  const hasText = Boolean(input.trim());
  const inputBlocked = disabled || uploading;

  return {
    hasText,
    canSubmit: hasText && !inputBlocked && !streaming,
    canRedirect: hasText && !inputBlocked && streaming,
    canStop: streaming && !stopRequested,
  };
}
