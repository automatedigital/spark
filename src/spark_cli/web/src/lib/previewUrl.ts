/**
 * Return true when a preview URL is served by the same machine as Spark.
 *
 * Spark advertises preview servers with the machine's mDNS `.local` hostname
 * as well as loopback addresses. Those pages can be embedded directly and
 * must not start the heavier streamed-browser fallback.
 */
export function isDirectPreviewUrl(url: string, dashboardHostname = window.location.hostname): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase();
    const dashboardHost = dashboardHostname.toLowerCase();
    return (
      host === "127.0.0.1" ||
      host === "localhost" ||
      host === "::1" ||
      host === "[::1]" ||
      host.endsWith(".local") ||
      (!!dashboardHost && host === dashboardHost)
    );
  } catch {
    return false;
  }
}
