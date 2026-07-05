export type ChatScrollMode = "following" | "detached" | "pending-new-message" | "jumping-to-bottom";

export interface ChatScrollMetrics {
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
}

export interface ChatScrollState {
  mode: ChatScrollMode;
  lastItemCount: number;
  anchorId: string | null;
}

export const DEFAULT_BOTTOM_THRESHOLD_PX = 120;
export const USER_DETACH_THRESHOLD_PX = 240;

export function initialChatScrollState(itemCount = 0): ChatScrollState {
  return {
    mode: "following",
    lastItemCount: itemCount,
    anchorId: null,
  };
}

export function distanceFromBottom(metrics: ChatScrollMetrics): number {
  return Math.max(0, metrics.scrollHeight - metrics.scrollTop - metrics.clientHeight);
}

export function isNearBottom(metrics: ChatScrollMetrics, thresholdPx = DEFAULT_BOTTOM_THRESHOLD_PX): boolean {
  return distanceFromBottom(metrics) < thresholdPx;
}

export function reduceChatScrollState(
  state: ChatScrollState,
  event:
    | { type: "session-reset"; itemCount?: number }
    | { type: "user-scroll"; metrics: ChatScrollMetrics; anchorId?: string | null }
    | { type: "items-changed"; itemCount: number }
    | { type: "stream-tick"; metrics: ChatScrollMetrics }
    | { type: "jump-to-bottom"; itemCount?: number }
    | { type: "jump-settle"; metrics: ChatScrollMetrics; itemCount?: number }
    | { type: "jump-complete"; itemCount?: number },
): ChatScrollState {
  switch (event.type) {
    case "session-reset":
      return initialChatScrollState(event.itemCount ?? 0);
    case "user-scroll": {
      const following = distanceFromBottom(event.metrics) < USER_DETACH_THRESHOLD_PX;
      return {
        ...state,
        mode: following ? "following" : "detached",
        anchorId: following ? null : event.anchorId ?? state.anchorId,
      };
    }
    case "items-changed": {
      if (event.itemCount === state.lastItemCount) return state;
      if (state.mode === "detached") {
        return { ...state, lastItemCount: event.itemCount, mode: "pending-new-message" };
      }
      return { ...state, lastItemCount: event.itemCount, mode: "jumping-to-bottom", anchorId: null };
    }
    case "stream-tick":
      if (state.mode === "detached" || state.mode === "pending-new-message" || state.mode === "jumping-to-bottom") return state;
      return isNearBottom(event.metrics) || state.mode === "following"
        ? { ...state, mode: "following", anchorId: null }
        : { ...state, mode: "detached" };
    case "jump-to-bottom":
      return {
        mode: "jumping-to-bottom",
        lastItemCount: event.itemCount ?? state.lastItemCount,
        anchorId: null,
      };
    case "jump-settle": {
      // Only complete a jump once the viewport is measurably at the bottom.
      // Virtualized rows are measured after the first scrollToIndex, growing
      // scrollHeight; staying in "jumping-to-bottom" lets the caller re-clamp
      // until the measured size stabilizes.
      if (state.mode !== "jumping-to-bottom") return state;
      const settledCount = event.itemCount ?? state.lastItemCount;
      if (isNearBottom(event.metrics)) {
        return { mode: "following", lastItemCount: settledCount, anchorId: null };
      }
      return { ...state, lastItemCount: settledCount };
    }
    case "jump-complete":
      return {
        mode: "following",
        lastItemCount: event.itemCount ?? state.lastItemCount,
        anchorId: null,
      };
  }
}

export function shouldAutoScrollChat(
  state: ChatScrollState,
  options: {
    countChanged: boolean;
    streaming: boolean;
    metrics: ChatScrollMetrics;
  },
): boolean {
  if (state.mode === "detached" || state.mode === "pending-new-message") return false;
  if (state.mode === "jumping-to-bottom") return true;
  if (options.countChanged) return true;
  return options.streaming && (state.mode === "following" || isNearBottom(options.metrics));
}
