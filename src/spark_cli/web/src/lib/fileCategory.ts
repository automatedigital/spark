/** Classify a workspace file for preview purposes, from its MIME type and name. */
export function getFileCategory(mime: string, filename: string): "text" | "image" | "video" | "binary" {
  if (mime.startsWith("image/")) return "image";
  if (mime.startsWith("video/")) return "video";
  if (
    mime.startsWith("text/") ||
    ["application/json", "application/yaml", "application/xml"].includes(mime)
  )
    return "text";
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const textExts = new Set([
    "ts", "tsx", "js", "jsx", "py", "md", "txt", "yaml", "yml",
    "json", "html", "css", "sh", "toml", "env", "ini", "cfg",
  ]);
  return textExts.has(ext) ? "text" : "binary";
}
