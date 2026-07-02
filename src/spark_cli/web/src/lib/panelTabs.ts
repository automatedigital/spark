export const MIDDLE_MOUSE_BUTTON = 1;

export function isMiddleClickCloseIntent(button: number, targetTab: string, activeTab: string) {
  return button === MIDDLE_MOUSE_BUTTON && targetTab === activeTab;
}
