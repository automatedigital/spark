export const COMPOSER_WIDE_ONLY = "hidden min-[1024px]:flex";
export const COMPOSER_WIDE_ONLY_BLOCK = "hidden min-w-0 min-[1024px]:block";
export const COMPOSER_COMPACT_ONLY = "min-[1024px]:hidden";

export type ComposerLayout = "compact" | "wide";

/** Keep the CSS breakpoint and the acceptance contract in one place. */
export function composerLayoutForWidth(width: number): ComposerLayout {
  return width >= 1024 ? "wide" : "compact";
}

export const COMPOSER_A11Y_LABELS = {
  input: "Message composer",
  attachments: "Add attachments",
  more: "More composer options",
  send: "Send message",
  stop: "Stop response",
  redirect: "Redirect with this message",
} as const;
