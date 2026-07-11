export const LIVE_STREAM_WINDOW_CHARS = 64 * 1024;

export interface LiveStreamWindow {
  content: string;
  totalChars: number;
  omittedChars: number;
  fenceCount: number;
}

function countFences(text: string): number {
  let count = 0;
  for (let index = text.indexOf("```"); index !== -1; index = text.indexOf("```", index + 3)) {
    count += 1;
  }
  return count;
}

/**
 * Keep React's live transcript state bounded regardless of the total response
 * size. The backend owns the complete stream and replaces this window from
 * saved history once the turn finishes.
 */
export function windowLiveStream(
  previous: Pick<LiveStreamWindow, "content" | "totalChars" | "fenceCount"> | null,
  appended: string,
  totalChars = (previous?.totalChars ?? 0) + appended.length,
): LiveStreamWindow {
  const combined = `${previous?.content ?? ""}${appended}`;
  const content = combined.length > LIVE_STREAM_WINDOW_CHARS
    ? combined.slice(-LIVE_STREAM_WINDOW_CHARS)
    : combined;
  return {
    content,
    totalChars,
    omittedChars: Math.max(0, totalChars - content.length),
    // Scanning is capped by LIVE_STREAM_WINDOW_CHARS, so work stays constant
    // as the complete response grows and the estimate matches visible text.
    fenceCount: countFences(content),
  };
}

export function snapshotLiveStream(text: string, totalChars = text.length): LiveStreamWindow {
  const content = text.length > LIVE_STREAM_WINDOW_CHARS
    ? text.slice(-LIVE_STREAM_WINDOW_CHARS)
    : text;
  return {
    content,
    totalChars,
    omittedChars: Math.max(0, totalChars - content.length),
    fenceCount: countFences(content),
  };
}
