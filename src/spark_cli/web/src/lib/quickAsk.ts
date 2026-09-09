export type QuickAskDestination = { kind: "chat" } | { kind: "project"; slug: string };
export interface QuickAskCapture { prompt: string; destination: QuickAskDestination; sessionId?: string | null; }
export function normalizeQuickAsk(value: QuickAskCapture): QuickAskCapture {
  return { ...value, prompt: value.prompt.trim(), sessionId: value.sessionId ?? null };
}
export function quickAskDestinationLabel(destination: QuickAskDestination): string {
  return destination.kind === "chat" ? "New standalone chat" : `Project: ${destination.slug}`;
}
