/** Window-level navigation events shared by controls outside AppShell. */

export const OPEN_SETTINGS_EVENT = "spark-open-settings";

export function emitOpenSettings(): void {
  window.dispatchEvent(new CustomEvent(OPEN_SETTINGS_EVENT));
}
