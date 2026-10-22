import React from "react";
import { createRoot } from "react-dom/client";
import CronPage from "../../src/pages/CronPage";
import { I18nProvider } from "../../src/i18n";
import "../../src/index.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode><I18nProvider><CronPage /></I18nProvider></React.StrictMode>,
);
