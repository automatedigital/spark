import { useEffect, useRef, useState } from "react";

/**
 * Renders a thread title that "types on" character-by-character whenever the
 * title changes after mount — e.g. when a freshly created thread receives its
 * auto-generated name over SSE. On first render (existing threads) the full
 * title is shown immediately with no animation.
 */
export function TypeOnTitle({
  text,
  className,
  speed = 26,
}: {
  text: string;
  className?: string;
  speed?: number;
}) {
  const [display, setDisplay] = useState(text);
  const prevRef = useRef(text);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const prev = prevRef.current;
    prevRef.current = text;
    if (text === prev) return;

    // Animate on live changes only; honour reduced-motion preferences.
    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !text) {
      setDisplay(text);
      return;
    }

    if (timerRef.current) clearInterval(timerRef.current);
    let i = 0;
    setDisplay("");
    timerRef.current = setInterval(() => {
      i += 1;
      setDisplay(text.slice(0, i));
      if (i >= text.length && timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    }, speed);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [text, speed]);

  const typing = display.length < text.length;

  return (
    <span className={className}>
      {display}
      {typing && (
        <span className="ml-px inline-block w-px animate-pulse align-baseline text-current opacity-70">
          |
        </span>
      )}
    </span>
  );
}
