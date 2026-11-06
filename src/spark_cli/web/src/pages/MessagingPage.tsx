import { lazy } from "react";

// Resolve shared Settings dependencies inside the existing Suspense boundary.
const Content = lazy(() => import("@/components/settings/MessagingPage"));
export default function MessagingPage() {
  return <Content />;
}
