import type { VirtualItem } from "@tanstack/react-virtual";

export interface SidebarScrollAnchor {
  key: string;
  delta: number;
  scrollTop: number;
}

export function captureSidebarScrollAnchor(
  virtualizer: { getVirtualItemForOffset: (offset: number) => VirtualItem | undefined },
  scrollTop: number,
): SidebarScrollAnchor | null {
  // React's onScroll can run before the virtualizer's native offset listener.
  // Its rendered/overscanned range can therefore still describe the old scroll
  // position. Search the complete measured model using the actual DOM offset.
  const first = virtualizer.getVirtualItemForOffset(scrollTop);
  return first ? { key: String(first.key), delta: scrollTop - first.start, scrollTop } : null;
}
