import { lazy } from "react";

// Resolve shared Settings dependencies inside the existing Suspense boundary.
const Content = lazy(() => import("@/components/settings/ConnectorsPage"));
export default function ConnectorsPage() {
  return <Content />;
}
