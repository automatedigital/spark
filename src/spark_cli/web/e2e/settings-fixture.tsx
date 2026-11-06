/* eslint-disable react-refresh/only-export-components -- standalone browser acceptance entry */
import { lazy, Suspense, useState } from "react";
import { createRoot } from "react-dom/client";
import { I18nProvider } from "../src/i18n";
import { WebUIThemeProvider } from "../src/lib/theme";
import { setRemoteConnection } from "../src/lib/apiHelpers";
import { setSidebarPreferenceScope } from "../src/lib/sidebarPrefs";
import "../src/index.css";
const SettingsPanel = lazy(() => import("../src/components/SettingsPanel"));
setSidebarPreferenceScope("/synthetic/profile-a");
function Fixture() {
  const [open, setOpen] = useState(false);
  return <I18nProvider><WebUIThemeProvider>
    <button onClick={() => setOpen(true)}>Open settings fixture</button>
    <button onClick={() => setRemoteConnection("http://synthetic-remote.invalid", "synthetic-token")}>Switch fixture remote</button>
    <button onClick={() => setSidebarPreferenceScope("/synthetic/profile-b")}>Switch fixture profile</button>
    {open && <Suspense fallback={<p>Loading settings</p>}><SettingsPanel onClose={() => setOpen(false)} /></Suspense>}
  </WebUIThemeProvider></I18nProvider>;
}
createRoot(document.getElementById("root")!).render(<Fixture />);
