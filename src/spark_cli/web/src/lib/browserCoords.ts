/** Server-side browser viewport (must match preview_browser._VIEWPORT). */
export const STREAM_VIEWPORT = { width: 1280, height: 800 };

/**
 * Map a pointer event on the rendered <img> to real viewport coordinates.
 * The frame is captured at viewport size but displayed scaled (object-contain),
 * so we undo letterboxing + scale. Returns null for clicks in the letterbox bars.
 */
export function mapToViewport(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number; width: number; height: number },
  viewport = STREAM_VIEWPORT,
): { x: number; y: number } | null {
  if (rect.width <= 0 || rect.height <= 0) return null;
  const scale = Math.min(rect.width / viewport.width, rect.height / viewport.height);
  const drawnW = viewport.width * scale;
  const drawnH = viewport.height * scale;
  const offsetX = (rect.width - drawnW) / 2;
  const offsetY = (rect.height - drawnH) / 2;
  const localX = clientX - rect.left - offsetX;
  const localY = clientY - rect.top - offsetY;
  if (localX < 0 || localY < 0 || localX > drawnW || localY > drawnH) return null;
  return {
    x: Math.round(localX / scale),
    y: Math.round(localY / scale),
  };
}
