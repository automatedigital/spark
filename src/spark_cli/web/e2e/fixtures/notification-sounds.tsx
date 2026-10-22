import { createRoot } from "react-dom/client";
import { NotificationBell } from "../../src/components/NotificationBell";
import "../../src/index.css";

createRoot(document.getElementById("root")!).render(<div style={{ padding: 40, display: "flex", justifyContent: "flex-end" }}><NotificationBell /></div>);
