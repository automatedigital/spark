import { lazy } from "react";

// Resolve shared Settings dependencies inside the existing Suspense boundary.
const Content = lazy(() => import("@/components/settings/SkillsToolsPage"));
export default function SkillsToolsPage() {
  return <Content />;
}
