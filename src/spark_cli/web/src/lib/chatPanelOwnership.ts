import { sidebarPreferenceKey, sidebarPreferenceScopeGeneration } from "./sidebarPrefs";
import { apiConnectionGeneration } from "./apiHelpers";

export interface PanelRequest {
  ownerToken: number;
  scope: string;
  requestGeneration: number;
  previousID: string | null;
}

export interface OwnedSessionAdoption extends PanelRequest {
  nextID: string;
  reason: "send-continuation" | "fork";
}

export interface ChatPanelOwner {
  ownerToken: number;
  scope: string;
  scopeGeneration: number;
  backendGeneration: number;
  isCurrent: () => boolean;
  beginRequest: () => PanelRequest | null;
}

export function isChatPanelScopeCurrent(owner: ChatPanelOwner): boolean {
  return owner.scope === sidebarPreferenceKey("chat")
    && owner.scopeGeneration === sidebarPreferenceScopeGeneration()
    && owner.backendGeneration === apiConnectionGeneration();
}

export interface ChatScrollBookmark {
  top: number;
  anchorId: string | null;
  offset: number;
}

// Page-owned navigation identity. This retains exactly one owner, never panels,
// controllers, callbacks supplied by a panel, DOM nodes or transcript objects.
export class ChatPanelOwnership {
  private serial = 0;
  private active = true;
  private current: (ChatPanelOwner & { sessionId: string | null; requestGeneration: number }) | null = null;
  readonly bookmarks = new Map<string, ChatScrollBookmark>();

  activate(): void { this.active = true; }
  retire(): void { this.active = false; }

  navigate(scope: string, sessionId: string | null, scopeGeneration = 0, backendGeneration = 0): ChatPanelOwner {
    if (this.current?.scope === scope && this.current.scopeGeneration === scopeGeneration && this.current.backendGeneration === backendGeneration && this.current.sessionId === sessionId) return this.current;
    const ownerToken = ++this.serial;
    const isCurrent = () => this.active && this.current?.ownerToken === ownerToken && this.current.scope === scope;
    const beginRequest = (): PanelRequest | null => {
      if (!isCurrent() || !this.current) return null;
      return { ownerToken, scope, requestGeneration: ++this.current.requestGeneration, previousID: this.current.sessionId };
    };
    this.current = { ownerToken, scope, scopeGeneration, backendGeneration, sessionId, requestGeneration: 0, isCurrent, beginRequest };
    return this.current;
  }

  adopt(request: OwnedSessionAdoption, liveScope: string, liveScopeGeneration = this.current?.scopeGeneration, liveBackendGeneration = this.current?.backendGeneration): boolean {
    const owner = this.current;
    if (!this.active || !owner || liveScope !== owner.scope || liveScopeGeneration !== owner.scopeGeneration || liveBackendGeneration !== owner.backendGeneration || request.scope !== owner.scope
      || request.ownerToken !== owner.ownerToken || request.requestGeneration !== owner.requestGeneration
      || request.previousID !== owner.sessionId || !request.nextID) return false;
    // Only an acknowledged send may change the selected ID without retiring
    // the view. Forks and ordinary navigation always allocate another owner.
    if (request.reason === "send-continuation") owner.sessionId = request.nextID;
    return true;
  }

  saveBookmark(scope: string, sessionId: string, bookmark: ChatScrollBookmark | null): void {
    const key = JSON.stringify([scope, sessionId]);
    this.bookmarks.delete(key);
    if (!bookmark) return;
    this.bookmarks.set(key, { top: bookmark.top, anchorId: bookmark.anchorId, offset: bookmark.offset });
    // Bookmarks are optional viewport hints, bounded independently of sessions.
    if (this.bookmarks.size > 100) this.bookmarks.delete(this.bookmarks.keys().next().value!);
  }

  readBookmark(scope: string, sessionId: string): ChatScrollBookmark | null {
    return this.bookmarks.get(JSON.stringify([scope, sessionId])) ?? null;
  }
}

