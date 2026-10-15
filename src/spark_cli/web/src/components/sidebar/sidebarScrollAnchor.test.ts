import { describe, expect, it } from "vitest";
import { Virtualizer } from "@tanstack/react-virtual";
import { captureSidebarScrollAnchor } from "./sidebarScrollAnchor";

function model(keys: string[], offset: number) {
  return new Virtualizer<HTMLDivElement, HTMLDivElement>({
    count: keys.length,
    getScrollElement: () => null,
    getItemKey: (index) => keys[index],
    estimateSize: () => 32,
    initialRect: { width: 240, height: 300 },
    initialOffset: offset,
    overscan: 8,
    observeElementRect: () => undefined,
    observeElementOffset: () => undefined,
    scrollToFn: () => undefined,
  });
}

describe("sidebar scroll anchors", () => {
  it("captures a native upward jump before the virtualizer observes the offset", () => {
    const keys = Array.from({ length: 100 }, (_, index) => `project-session:alpha:s${index}`);
    const virtualizer = model(keys, 2400);
    // The old mounted range has no rows at the new DOM offset. This used to
    // select an overscanned row far below the viewport with a negative delta.
    expect(virtualizer.getVirtualItems()[0].start).toBeGreaterThan(600);
    expect(captureSidebarScrollAnchor(virtualizer, 600)).toEqual({
      key: keys[18], delta: 24, scrollTop: 600,
    });
  });

  it("retains the placement and pixel delta when paging inserts rows above it", () => {
    const keys = Array.from({ length: 50 }, (_, index) => `project-session:alpha:s${index}`);
    const anchor = captureSidebarScrollAnchor(model(keys, 1300), 600)!;
    const next = model(["pinned:s18", ...keys.slice(0, 10), "project-session:alpha:live", ...keys.slice(10)], 600);
    next.getVirtualItems();
    const target = next.measurementsCache.find((item) => item.key === anchor.key)!;
    expect(target.start + anchor.delta).toBe(664);
    expect(captureSidebarScrollAnchor(next, 664)).toEqual({ ...anchor, scrollTop: 664 });
  });

  it("has no anchor for an empty model", () => {
    expect(captureSidebarScrollAnchor(model([], 0), 0)).toBeNull();
  });
});
