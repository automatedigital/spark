import { API_CONNECTION_EVENT, apiConnectionGeneration, getApiBase } from "./apiHelpers";
import { SIDEBAR_SCOPE_EVENT, sidebarPreferenceScopeGeneration } from "./sidebarPrefs";

export function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

/** One view lifetime; each read has its own controller. Never use for mutations. */
export class ReadOwner {
  private retired = false;
  private readonly controllers = new Set<AbortController>();
  private readonly backend = getApiBase();
  private readonly connection = apiConnectionGeneration();
  private readonly profile = sidebarPreferenceScopeGeneration();
  private readonly onScopeChange = () => { if (!this.isCurrent()) this.retire(); };

  private readonly viewCurrent: () => boolean;

  constructor(viewCurrent: () => boolean) {
    this.viewCurrent = viewCurrent;
    if (typeof window !== "undefined") {
      window.addEventListener(API_CONNECTION_EVENT, this.onScopeChange);
      window.addEventListener(SIDEBAR_SCOPE_EVENT, this.onScopeChange);
    }
  }

  isCurrent(): boolean {
    return !this.retired && this.viewCurrent() && this.backend === getApiBase()
      && this.connection === apiConnectionGeneration()
      && this.profile === sidebarPreferenceScopeGeneration();
  }

  retire(): void {
    this.retired = true;
    if (typeof window !== "undefined") {
      window.removeEventListener(API_CONNECTION_EVENT, this.onScopeChange);
      window.removeEventListener(SIDEBAR_SCOPE_EVENT, this.onScopeChange);
    }
    for (const controller of this.controllers) controller.abort();
    this.controllers.clear();
  }

  async read<T>(request: (signal: AbortSignal) => Promise<T>): Promise<T> {
    const controller = new AbortController();
    const check = () => {
      if (!this.isCurrent()) throw new DOMException("Read owner retired", "AbortError");
    };
    check();
    this.controllers.add(controller);
    try {
      const result = await request(controller.signal);
      check();
      return result;
    } catch (error) {
      check();
      throw error;
    } finally {
      // Only this read owns its registration; late cleanup cannot remove a successor.
      this.controllers.delete(controller);
    }
  }
}
