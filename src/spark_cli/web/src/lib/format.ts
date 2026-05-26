/**
 * Format a token count as a human-readable string (e.g. 1M, 128K, 4096).
 * Strips trailing ".0" for clean round numbers.
 */
export function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}K`;
  return String(n);
}

/**
 * Format the time until (or since) a future date, e.g. "in 4h 12m", "in 2 days", "overdue".
 */
export function timeUntil(date: Date): string {
  const diffMs = date.getTime() - Date.now();
  const past = diffMs < 0;
  const abs = Math.abs(diffMs);
  const totalSecs = Math.floor(abs / 1000);
  const mins = Math.floor(totalSecs / 60) % 60;
  const hours = Math.floor(totalSecs / 3600) % 24;
  const days = Math.floor(totalSecs / 86400);

  let label: string;
  if (days >= 2) label = `${days} days`;
  else if (days === 1) label = `1 day ${hours}h`;
  else if (hours > 0) label = `${hours}h ${mins}m`;
  else if (mins > 0) label = `${mins}m`;
  else label = `${totalSecs}s`;

  return past ? `overdue ${label} ago` : `in ${label}`;
}
