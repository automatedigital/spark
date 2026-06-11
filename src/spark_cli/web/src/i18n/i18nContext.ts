import { createContext, useContext } from "react";
import type { Translations } from "./types";
import { en } from "./en";

export interface I18nContextValue {
  t: Translations;
}

export const I18nContext = createContext<I18nContextValue>({
  t: en,
});

export function useI18n() {
  return useContext(I18nContext);
}
