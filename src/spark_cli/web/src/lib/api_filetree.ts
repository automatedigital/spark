import { fetchJSON } from "./apiHelpers";
import type { WorkspaceFileNode } from "./apiTypes";

export interface FileTreeNode extends WorkspaceFileNode {
  symlink?: boolean;
  children?: FileTreeNode[];
}

export interface DirectoryPage {
  path: string;
  entries: FileTreeNode[];
  revision: string;
  next_cursor: string | null;
}

export function readDirectory(slug: string, path: string, hidden: boolean, signal: AbortSignal, cursor = "") {
  const query = new URLSearchParams({ path, show_hidden: String(hidden), paged: "true", limit: "200", cursor });
  return fetchJSON<DirectoryPage>(`/api/workspace/projects/${encodeURIComponent(slug)}/list?${query}`, { signal });
}
