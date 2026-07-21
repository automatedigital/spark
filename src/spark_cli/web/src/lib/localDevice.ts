export type LocalDeviceLabel = "Windows PC" | "Mac" | "Linux computer" | "computer";

/** Return a human-readable name for the machine hosting the desktop app. */
export function localDeviceLabel(
  userAgent = typeof navigator === "undefined" ? "" : navigator.userAgent,
  platform = typeof navigator === "undefined" ? "" : navigator.platform,
): LocalDeviceLabel {
  const signature = `${userAgent} ${platform}`;
  if (/Windows/i.test(signature)) return "Windows PC";
  if (/Macintosh|Mac OS X|MacIntel/i.test(signature)) return "Mac";
  if (/Linux|X11/i.test(signature)) return "Linux computer";
  return "computer";
}
