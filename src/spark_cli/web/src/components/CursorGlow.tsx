import { useEffect, useRef } from "react";
import {
  createFrameScheduler,
  shouldTrackDecorativePointer,
  type FrameScheduler,
} from "@/lib/renderHealth";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

export function CursorGlow() {
  const glowRef = useRef<HTMLDivElement>(null);
  const latestPointerRef = useRef({ x: -1_000, y: -1_000 });

  useEffect(() => {
    const glow = glowRef.current;
    if (!glow) return;

    const motionPreference = window.matchMedia(REDUCED_MOTION_QUERY);
    let scheduler: FrameScheduler<boolean> | null = null;

    const createPointerScheduler = () => createFrameScheduler<boolean>(
        () => {
          const { x, y } = latestPointerRef.current;
          glow.style.transform = `translate3d(${x}px, ${y}px, 0) translate(-50%, -50%)`;
        },
        window.requestAnimationFrame.bind(window),
        window.cancelAnimationFrame.bind(window),
      );

    const handlePointerMove = (event: PointerEvent) => {
      latestPointerRef.current = { x: event.clientX, y: event.clientY };
      scheduler?.schedule(true);
    };

    const syncMotionPreference = () => {
      window.removeEventListener("pointermove", handlePointerMove);
      scheduler?.dispose();
      scheduler = null;
      const trackingEnabled = shouldTrackDecorativePointer(motionPreference.matches);
      glow.hidden = !trackingEnabled;
      if (trackingEnabled) {
        scheduler = createPointerScheduler();
        window.addEventListener("pointermove", handlePointerMove, { passive: true });
      }
    };

    syncMotionPreference();
    motionPreference.addEventListener("change", syncMotionPreference);

    return () => {
      motionPreference.removeEventListener("change", syncMotionPreference);
      window.removeEventListener("pointermove", handlePointerMove);
      scheduler?.dispose();
    };
  }, []);

  return <div ref={glowRef} className="cursor-blob" aria-hidden="true" />;
}
