import { createContext, useCallback, useContext, useRef, useState, useEffect, type Dispatch, type SetStateAction } from "react";
import { apiConnectionGeneration } from "@/lib/apiHelpers";
import { sidebarPreferenceKey, sidebarPreferenceScopeGeneration } from "@/lib/sidebarPrefs";

export function settingsDraftScope() {
  return JSON.stringify([sidebarPreferenceKey("settings"), sidebarPreferenceScopeGeneration(), apiConnectionGeneration()]);
}

/** One open dialog owns drafts. No DOM, effects, responses or disk persistence. */
export class SettingsDraftOwner {
  readonly values = new Map<string, unknown>();
  readonly scope: string;
  constructor(scope: string) { this.scope = scope; }
  read<T>(key: string, initial: T): T {
    return this.values.has(key) ? this.values.get(key) as T : initial;
  }
  write<T>(key: string, value: T, liveScope: string): boolean {
    if (liveScope !== this.scope) return false;
    this.values.set(key, value);
    return true;
  }
}

export const DraftContext = createContext<{ owner: SettingsDraftOwner; tab: string } | null>(null);

/** Outside Settings, pages keep their normal component-local state. */
export function useSettingsDraft<T>(key: string, initial: T): [T, Dispatch<SetStateAction<T>>] {
  const context = useContext(DraftContext);
  const fullKey = `${context?.tab ?? ""}:${key}`;
  const [value, setValue] = useState<T>(() => context?.owner.read(fullKey, initial) ?? initial);
  const currentValue = useRef(value);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const setDraft = useCallback<Dispatch<SetStateAction<T>>>((update) => {
    if (!alive.current || (context && context.owner.scope !== settingsDraftScope())) return;
    const next = typeof update === "function" ? (update as (value: T) => T)(currentValue.current) : update;
    currentValue.current = next;
    // Capture before React can unmount this tab in the same event batch.
    context?.owner.write(fullKey, next, settingsDraftScope());
    setValue(next);
  }, [context, fullKey]);
  return [value, setDraft];
}
