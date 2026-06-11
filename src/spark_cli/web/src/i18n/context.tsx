import { type ReactNode } from "react";
import { en } from "./en";
import { I18nContext } from "./i18nContext";

export function I18nProvider({ children }: { children: ReactNode }) {
  return <I18nContext.Provider value={{ t: en }}>{children}</I18nContext.Provider>;
}
