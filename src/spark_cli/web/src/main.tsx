import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";
import { I18nProvider } from "./i18n";
import { UpdateModalProvider } from "./lib/UpdateModalContext";

createRoot(document.getElementById("root")!).render(
  <I18nProvider>
    <UpdateModalProvider>
      <App />
    </UpdateModalProvider>
  </I18nProvider>,
);
