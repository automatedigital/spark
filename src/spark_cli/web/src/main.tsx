import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { I18nProvider } from "./i18n";
import { UpdateModalProvider } from "./lib/UpdateModalContext";
import { WebUIThemeProvider } from "./lib/theme";

createRoot(document.getElementById("root")!).render(
  <I18nProvider>
    <WebUIThemeProvider>
      <UpdateModalProvider>
        <App />
      </UpdateModalProvider>
    </WebUIThemeProvider>
  </I18nProvider>,
);
