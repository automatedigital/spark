import type { FileListEntry } from "@/lib/api";

export const ROOT_PATH = ".";

function stripWrappingQuotes(value: string): string {
  let next = value.trim();
  while (next.length >= 2) {
    const first = next[0];
    const last = next[next.length - 1];
    if ((first === "'" && last === "'") || (first === '"' && last === '"') || (first === "`" && last === "`")) {
      next = next.slice(1, -1).trim();
      continue;
    }
    break;
  }
  return next;
}

function cleanDisplayedPath(path: string): string {
  return stripWrappingQuotes(path).replace(/\\/g, "/").replace(/\/+/g, "/");
}

function safeRelativePath(path: string): string | null {
  const parts = path
    .replace(/^\.\/+/, "")
    .split("/")
    .filter((part) => part.length > 0 && part !== ".");

  if (parts.length === 0 || parts.some((part) => part === "..")) return null;
  return parts.join("/");
}

function isAbsoluteDisplayedPath(path: string): boolean {
  return path.startsWith("/") || path.startsWith("~/") || /^[A-Za-z]:\//.test(path);
}

export function normalizeDisplayedPath(path: string): string {
  return cleanDisplayedPath(path);
}

export function workspaceRelativePath(path: string): string | null {
  const normalized = cleanDisplayedPath(path);
  if (!normalized) return null;

  const workspaceMatch = normalized.match(/(?:^~\/|\/)\.spark\/(?:profiles\/[^/]+\/)?workspace\/(.+)$/);
  if (workspaceMatch?.[1]) return safeRelativePath(workspaceMatch[1]);

  if (isAbsoluteDisplayedPath(normalized)) return null;
  return safeRelativePath(normalized);
}

export function parentDirForFile(path: string): string {
  const rel = workspaceRelativePath(path);
  if (!rel) return ROOT_PATH;
  const parts = rel.split("/").filter(Boolean);
  parts.pop();
  return parts.length ? parts.join("/") : ROOT_PATH;
}

export function fileEntryFromPath(path: string, fallbackName?: string): FileListEntry {
  const rel = workspaceRelativePath(path);
  const cleanPath = rel ?? cleanDisplayedPath(path);
  const cleanFallback = fallbackName ? stripWrappingQuotes(fallbackName) : "";
  return {
    name: cleanFallback || cleanPath.split("/").filter(Boolean).pop() || "file",
    path: cleanPath,
    type: "file",
  };
}
