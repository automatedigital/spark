import { lazy, type ComponentProps } from "react";

// Resolve shared Settings dependencies inside the existing Suspense boundary.
const Content = lazy(() => import("@/components/settings/SettingsPanelContent"));
export default function SettingsPanel(props: ComponentProps<typeof Content>) {
  return <Content {...props} />;
}
