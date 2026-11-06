import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/chatTranscriptMerge";

/** Only text-only live replacements can wait for a frame. Decisions, tool and
 * terminal transitions (including metadata changes) must present immediately. */
export function isTimelineTextDelta(previous: readonly ChatMessage[], next: readonly ChatMessage[]): boolean {
  if (previous.length !== next.length || !next.length) return false;
  let changed = false;
  for (let index = 0; index < next.length; index += 1) {
    const before = previous[index];
    const after = next[index];
    if (before === after) continue;
    if (before.id !== after.id || before.role !== after.role) return false;
    if (before.role !== "assistant" || after.role !== "assistant" || !before.streaming || !after.streaming) return false;
    const textKeys = new Set(["content", "renderRevision", "liveTotalChars", "liveOmittedChars"]);
    const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
    for (const key of keys) {
      if (!textKeys.has(key) && Reflect.get(before, key) !== Reflect.get(after, key)) return false;
    }
    changed = true;
  }
  return changed;
}

/** Presentation only: the controller retains every token and owns lifecycle. */
export function useTimelinePresentation(messages: ChatMessage[], sessionId: string | null): ChatMessage[] {
  const [presented, setPresented] = useState({ messages, sessionId });
  const frame = useRef<number | null>(null);
  const latest = useRef({ messages, sessionId });
  const defer = presented.sessionId === sessionId && isTimelineTextDelta(presented.messages, messages);

  useLayoutEffect(() => {
    latest.current = { messages, sessionId };
    if (!defer) {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
      if (presented.messages !== messages || presented.sessionId !== sessionId) setPresented({ messages, sessionId });
    } else if (frame.current === null) {
      frame.current = requestAnimationFrame(() => {
        frame.current = null;
        setPresented(latest.current);
      });
    }
  }, [defer, messages, sessionId, presented]);

  useLayoutEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
  }, []);

  return defer ? presented.messages : messages;
}

/** Keep memoized row callbacks stable while invoking the latest committed owner. */
export function useTimelineCallback<Args extends unknown[], Result>(callback: (...args: Args) => Result): (...args: Args) => Result {
  const latest = useRef(callback);
  useLayoutEffect(() => { latest.current = callback; }, [callback]);
  return useCallback((...args: Args) => latest.current(...args), []);
}
