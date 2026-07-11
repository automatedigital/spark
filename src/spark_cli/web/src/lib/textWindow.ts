export const COMPLETED_TEXT_WINDOW_CHARS = 128 * 1024;
export const REASONING_WINDOW_CHARS = 8 * 1024;

export interface BoundedText {
  text: string;
  totalChars: number;
  omittedChars: number;
}

export function boundText(text: string, limit: number, totalChars = text.length): BoundedText {
  const safeTotal = Math.max(totalChars, text.length);
  const visible = text.length > limit ? text.slice(-limit) : text;
  return {
    text: visible,
    totalChars: safeTotal,
    omittedChars: Math.max(0, safeTotal - visible.length),
  };
}

export function appendBoundedText(current: BoundedText, delta: string, limit: number): BoundedText {
  const combined = `${current.text}${delta}`;
  return boundText(combined, limit, current.totalChars + delta.length);
}
