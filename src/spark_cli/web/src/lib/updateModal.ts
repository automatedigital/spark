import { createContext, useContext } from "react";

export interface UpdateModalContextValue {
  updateAvailable: boolean;
  latestVersion: string | null;
  openUpdateModal: () => void;
  macUpdateAvailable: boolean;
  macLatestVersion: string | null;
  openMacUpdateModal: () => void;
}

export const UpdateModalContext = createContext<UpdateModalContextValue>({
  updateAvailable: false,
  latestVersion: null,
  openUpdateModal: () => {},
  macUpdateAvailable: false,
  macLatestVersion: null,
  openMacUpdateModal: () => {},
});

export function useUpdateModal() {
  return useContext(UpdateModalContext);
}
