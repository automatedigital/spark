export type OutputType =
  | { kind: "image"; url: string }
  | { kind: "audio"; url: string }
  | { kind: "video"; url: string }
  | { kind: "code"; language: string; path: string }
  | { kind: "text" };

const IMAGE_EXTS = new Set([".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"]);
const AUDIO_EXTS = new Set([".mp3", ".wav", ".ogg", ".m4a", ".flac", ".opus"]);
const VIDEO_EXTS = new Set([".mp4", ".webm", ".mov", ".avi", ".mkv"]);
const CODE_EXT_MAP: Record<string, string> = {
  ".py": "python", ".js": "javascript", ".ts": "typescript",
  ".tsx": "tsx", ".jsx": "jsx", ".sh": "bash", ".bash": "bash",
  ".rs": "rust", ".go": "go", ".rb": "ruby", ".java": "java",
  ".c": "c", ".cpp": "cpp", ".cs": "csharp", ".json": "json",
  ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".css": "css",
  ".html": "html", ".xml": "xml", ".sql": "sql", ".md": "markdown",
};

function isPathLike(value: string): boolean {
  const trimmed = value.trim();
  return (
    (trimmed.startsWith("/") || trimmed.startsWith("~/") || /^[A-Za-z]:\\/.test(trimmed)) &&
    !trimmed.includes("\n") &&
    trimmed.length < 512
  );
}

export function detectOutputType(value: string): OutputType {
  const trimmed = value.trim();
  if (!isPathLike(trimmed)) return { kind: "text" };

  const lastDot = trimmed.lastIndexOf(".");
  const ext = lastDot >= 0 ? trimmed.slice(lastDot).toLowerCase() : "";

  if (IMAGE_EXTS.has(ext)) return { kind: "image", url: `/api/files?path=${encodeURIComponent(trimmed)}` };
  if (AUDIO_EXTS.has(ext)) return { kind: "audio", url: `/api/files?path=${encodeURIComponent(trimmed)}` };
  if (VIDEO_EXTS.has(ext)) return { kind: "video", url: `/api/files?path=${encodeURIComponent(trimmed)}` };
  const lang = CODE_EXT_MAP[ext];
  if (lang) return { kind: "code", language: lang, path: trimmed };

  return { kind: "text" };
}
