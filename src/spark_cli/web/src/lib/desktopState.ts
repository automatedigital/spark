/** Presentation state persisted between desktop launches. Backend state remains authoritative. */
export interface DesktopWorkSurface {
  version: 1;
  page: string;
  selectedSessionId: string | null;
  sidebarExpanded: boolean;
  rightPanelOpen: boolean;
  rightPanelWidth: number;
  scrollAnchor: string | null;
  savedAt: number;
}

const KEY = "spark-desktop-work-surface-v1";

export function readDesktopWorkSurface(storage: Pick<Storage, "getItem"> = localStorage): DesktopWorkSurface | null {
  try {
    const raw = storage.getItem(KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<DesktopWorkSurface>;
    if (value.version !== 1 || typeof value.page !== "string") return null;
    return {
      version: 1,
      page: value.page,
      selectedSessionId: typeof value.selectedSessionId === "string" ? value.selectedSessionId : null,
      sidebarExpanded: Boolean(value.sidebarExpanded),
      rightPanelOpen: Boolean(value.rightPanelOpen),
      rightPanelWidth: typeof value.rightPanelWidth === "number" && Number.isFinite(value.rightPanelWidth)
        ? Math.max(240, Math.min(720, value.rightPanelWidth)) : 360,
      scrollAnchor: typeof value.scrollAnchor === "string" ? value.scrollAnchor : null,
      savedAt: typeof value.savedAt === "number" ? value.savedAt : Date.now(),
    };
  } catch { return null; }
}

export function writeDesktopWorkSurface(surface: Omit<DesktopWorkSurface, "version" | "savedAt">, storage: Pick<Storage, "setItem"> = localStorage): void {
  try { storage.setItem(KEY, JSON.stringify({ ...surface, version: 1, savedAt: Date.now() })); } catch { /* best effort */ }
}
