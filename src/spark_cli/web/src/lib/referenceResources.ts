/** Bounded reference reads only. No session history, credentials or mutations. */
import { apiConnectionGeneration, getApiBase, getDashboardToken } from "./apiHelpers";
import { sidebarPreferenceScopeGeneration } from "./sidebarPrefs";

export type ReferenceResource = "sidebar" | "cron" | "memory";
export const REFERENCE_TTL_MS = 60_000;
let lastCredential: string | null = null;
let credentialEpoch = 0;
export const referenceScope = () => {
  const credential = getDashboardToken();
  if (credential !== lastCredential) { lastCredential = credential; credentialEpoch += 1; }
  return `${getApiBase()}|${apiConnectionGeneration()}|${credentialEpoch}|${sidebarPreferenceScopeGeneration()}`;
};
export interface ResourceState<T> { data?: T; error?: unknown; updatedAt: number; stale: boolean }
interface Entry extends ResourceState<unknown> {
  revision: number;
  pending?: Promise<unknown>;
  controller?: AbortController;
}
const aborted = () => new DOMException("Reference read retired", "AbortError");

export class ReferenceResources {
  private scope = "";
  private entries = new Map<ReferenceResource, Entry>();
  private listeners = new Map<ReferenceResource, Set<() => void>>();
  private queued = new Map<ReferenceResource, ReturnType<typeof setTimeout>>();
  private currentScope: () => string;
  private now: () => number;
  constructor(currentScope = referenceScope, now = () => Date.now()) { this.currentScope = currentScope; this.now = now; }
  private syncScope() {
    const next = this.currentScope();
    if (next === this.scope) return;
    for (const entry of this.entries.values()) entry.controller?.abort();
    this.entries.clear();
    this.scope = next;
  }
  private entry(id: ReferenceResource) {
    this.syncScope();
    let entry = this.entries.get(id);
    if (!entry) { entry = { updatedAt: 0, stale: true, revision: 0 }; this.entries.set(id, entry); }
    return entry;
  }
  state<T>(id: ReferenceResource): ResourceState<T> {
    const entry = this.entry(id);
    return { data: entry.data as T | undefined, error: entry.error, updatedAt: entry.updatedAt,
      stale: entry.stale || this.now() - entry.updatedAt >= REFERENCE_TTL_MS };
  }
  invalidate(id: ReferenceResource) {
    const entry = this.entry(id);
    entry.stale = true;
    entry.error = undefined;
    entry.revision += 1;
  }
  /** One consumer's abort only retires its own promise; the shared read survives. */
  read<T>(id: ReferenceResource, loader: (signal: AbortSignal) => Promise<T>, signal?: AbortSignal): Promise<T> {
    if (signal?.aborted) return Promise.reject(aborted());
    const entry = this.entry(id);
    const scope = this.scope;
    if (!entry.pending && (entry.stale || this.now() - entry.updatedAt >= REFERENCE_TTL_MS)) {
      const revision = entry.revision;
      const controller = new AbortController();
      entry.controller = controller;
      entry.pending = Promise.resolve().then(() => {
        if (controller.signal.aborted || scope !== this.currentScope()) throw aborted();
        return loader(controller.signal);
      }).then((data) => {
        if (scope !== this.currentScope() || controller.signal.aborted) throw aborted();
        // A committed mutation/event arriving during the GET cannot be overwritten.
        if (entry.revision === revision) {
          entry.data = data; entry.updatedAt = this.now(); entry.stale = false; entry.error = undefined;
        }
        return data;
      }).catch((error: unknown) => {
        if (scope === this.currentScope() && entry.revision === revision) { entry.error = error; entry.stale = true; }
        throw error;
      }).finally(() => { entry.pending = undefined; entry.controller = undefined; });
    }
    const result = (entry.pending ?? Promise.resolve(entry.data)).then((data) => {
      if (scope !== this.currentScope()) throw aborted();
      if (entry.stale && !entry.error) return this.read(id, loader);
      return data as T;
    });
    if (!signal) return result;
    return new Promise<T>((resolve, reject) => {
      const abort = () => reject(aborted());
      signal.addEventListener("abort", abort, { once: true });
      result.then((data) => { if (!signal.aborted) resolve(data); }, reject)
        .finally(() => signal.removeEventListener("abort", abort));
    });
  }
  subscribe(id: ReferenceResource, listener: () => void) {
    const listeners = this.listeners.get(id) ?? new Set();
    this.listeners.set(id, listeners); listeners.add(listener);
    return () => { listeners.delete(listener); };
  }
  /** Focus, reconnect and events in the same burst share one refresh. */
  refresh(id: ReferenceResource, invalidate = false) {
    if (invalidate) this.invalidate(id);
    if (this.queued.has(id)) return;
    this.queued.set(id, setTimeout(() => {
      this.queued.delete(id);
      this.listeners.get(id)?.forEach((listener) => listener());
    }, 50));
  }
}
export const referenceResources = new ReferenceResources();
