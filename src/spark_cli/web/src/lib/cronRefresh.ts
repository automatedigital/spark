export const CRON_REFRESH_INTERVAL_MS = 15_000;

export function shouldRefreshCronJobs(visibilityState: DocumentVisibilityState): boolean {
  return visibilityState === "visible";
}
