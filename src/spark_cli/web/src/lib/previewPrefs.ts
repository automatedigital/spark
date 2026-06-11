const AUTO_OPEN_KEY = "spark-preview-autoopen";

/** Whether the right panel should jump to Preview when a dev server reports ready. */
export function previewAutoOpenEnabled(): boolean {
  return localStorage.getItem(AUTO_OPEN_KEY) !== "false";
}

export function setPreviewAutoOpen(enabled: boolean): void {
  localStorage.setItem(AUTO_OPEN_KEY, String(enabled));
}
